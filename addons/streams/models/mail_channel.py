# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api, tools, _
from odoo.exceptions import AccessError
from odoo.osv import expression

from .mail_message import STREAM_ACTIVITY, STREAM_CHANGE, STREAM_REL_TABLE

# Сколько изменений на запись отдаётся в ленту Changes за один запрос.
# Лента — сводка «что поменялось», а не полная история записи.
STREAMS_CHANGES_PER_RECORD = 20

_logger = logging.getLogger(__name__)


class MailChannel(models.Model):
    """Канал записи: групповое обсуждение конкретной записи (§3, §5)."""
    _inherit = 'mail.channel'

    channel_kind = fields.Selection(
        [
            ('record', 'Record'),
            ('changes', 'Changes'),
            ('notifications', 'Notifications'),
        ],
        string='Stream Kind',
        help="Record: discussion of a business document. "
             "Changes / Notifications: personal service channels.")
    res_model = fields.Char(
        string='Related Document Model', index=True)
    res_id = fields.Integer(
        string='Related Document ID', index=True)
    owner_user_id = fields.Many2one(
        'res.users', string='Stream Owner', ondelete='cascade',
        help="Owner of a personal Changes or Notifications channel.")
    company_id = fields.Many2one(
        'res.company', string='Company',
        help="Inherited from the source record of a record channel.")

    def init(self):
        super().init()
        tools.create_index(
            self._cr, 'mail_channel_streams_record_idx', self._table,
            ['res_model', 'res_id'])
        # Уникальность канала записи. Частичный индекс, а не _sql_constraints:
        # обычные каналы Discuss не имеют res_model/res_id и под ограничение
        # попадать не должны.
        self._cr.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = %s",
            ('mail_channel_streams_record_uniq',))
        if not self._cr.fetchone():
            self._cr.execute("""
                CREATE UNIQUE INDEX mail_channel_streams_record_uniq
                    ON mail_channel (res_model, res_id)
                 WHERE channel_kind = 'record'
            """)
        # Личный служебный канал у пользователя ровно один на вид (§8.3):
        # гонка двух параллельных подписок не должна плодить дубли.
        self._cr.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = %s",
            ('mail_channel_streams_owner_uniq',))
        if not self._cr.fetchone():
            self._cr.execute("""
                CREATE UNIQUE INDEX mail_channel_streams_owner_uniq
                    ON mail_channel (channel_kind, owner_user_id)
                 WHERE channel_kind IN ('changes', 'notifications')
                   AND owner_user_id IS NOT NULL
            """)

    # ------------------------------------------------------------
    # ПРИВЯЗКА СООБЩЕНИЙ
    # ------------------------------------------------------------

    @api.model
    def _streams_insert_links(self, pairs):
        """Батчевая вставка связей «сообщение ↔ канал».

        `pairs` — список кортежей (message_id, channel_id). ON CONFLICT
        опирается на первичный ключ m2m-таблицы, который Odoo создаёт по
        обоим колонкам.
        """
        if not pairs:
            return
        self.env['mail.message'].flush()
        self.env.cr.execute(
            """
            INSERT INTO %s (message_id, channel_id)
                 SELECT * FROM unnest(%%s::int[], %%s::int[])
            ON CONFLICT DO NOTHING
            """ % STREAM_REL_TABLE,
            ([pair[0] for pair in pairs], [pair[1] for pair in pairs]))

    def _streams_link_messages(self, messages):
        """Подшить сообщения к каналу."""
        self.ensure_one()
        if not messages:
            return
        self._streams_insert_links(
            [(message_id, self.id) for message_id in messages.ids])
        messages.invalidate_cache(
            fnames=['stream_channel_ids'], ids=messages.ids)

    def _streams_attach_history(self):
        """Подшить к каналу всю прежнюю историю сообщений записи (§5.1)."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return
        self.env['mail.message'].flush()
        self.env.cr.execute(
            """
            INSERT INTO %s (message_id, channel_id)
                 SELECT msg.id, %%s
                   FROM mail_message msg
                  WHERE msg.model = %%s
                    AND msg.res_id = %%s
                    AND msg.message_type != 'user_notification'
            ON CONFLICT DO NOTHING
            """ % STREAM_REL_TABLE,
            (self.id, self.res_model, self.res_id))
        self.env['mail.message'].invalidate_cache(
            fnames=['stream_channel_ids'])

    def _streams_merge_into(self, target):
        """Слить канал-источник в канал получателя (§5.6).

        Сообщения перелинковываются, участники объединяются, источник
        архивируется. Дубли связей снимаем до UPDATE: первичный ключ
        m2m-таблицы иначе не даст перенести пересечение.
        """
        self.ensure_one()
        target.ensure_one()
        self.env['mail.message'].flush()
        self.env.cr.execute(
            """
            DELETE FROM %(rel)s src
                  WHERE src.channel_id = %%s
                    AND EXISTS (SELECT 1 FROM %(rel)s tgt
                                 WHERE tgt.channel_id = %%s
                                   AND tgt.message_id = src.message_id)
            """ % {'rel': STREAM_REL_TABLE}, (self.id, target.id))
        self.env.cr.execute(
            "UPDATE %s SET channel_id = %%s WHERE channel_id = %%s"
            % STREAM_REL_TABLE, (target.id, self.id))
        self.env['mail.message'].invalidate_cache(
            fnames=['stream_channel_ids'])
        partner_ids = (self.channel_partner_ids - target.channel_partner_ids).ids
        if partner_ids:
            target.sudo().with_context(streams_sync=True).add_members(
                partner_ids=partner_ids)
        self.sudo().write({'active': False})
        _logger.info(
            'streams: канал %s слит в канал %s', self.id, target.id)

    # ------------------------------------------------------------
    # ЛИЧНЫЙ КАНАЛ CHANGES (§8.3)
    # ------------------------------------------------------------

    @api.model
    def _streams_get_changes_channel(self, user=None, create=True):
        """Личный канал изменений пользователя; создаётся лениво.

        Канал заводится при первой подписке на поля, а не всем подряд:
        у большинства пользователей подписок нет и пустой канал в
        сайдбаре им не нужен.
        """
        user = user or self.env.user
        if not user or not user.partner_id:
            return self.browse()
        channel = self.sudo().with_context(active_test=False).search([
            ('channel_kind', '=', 'changes'),
            ('owner_user_id', '=', user.id),
        ], limit=1)
        if channel:
            if not channel.active:
                channel.write({'active': True})
            return channel
        if not create:
            return self.browse()
        channel = self.sudo().with_context(
            streams_sync=True, mail_create_nosubscribe=True).create({
                'name': 'Changes',
                'channel_type': 'channel',
                'public': 'private',
                'channel_kind': 'changes',
                'owner_user_id': user.id,
                'channel_last_seen_partner_ids': [
                    (0, 0, {'partner_id': user.partner_id.id})],
            })
        # ядровый `create` всегда добавляет участником того, кто создаёт;
        # изменение мог записать кто угодно, а канал личный
        creator_partner = self.env.user.partner_id
        if creator_partner and creator_partner != user.partner_id:
            channel.sudo().with_context(
                streams_sync=True).channel_last_seen_partner_ids.filtered(
                    lambda member: member.partner_id == creator_partner
            ).unlink()
        _logger.info(
            'streams: создан личный канал Changes %s для пользователя %s',
            channel.id, user.id)
        return channel

    # ------------------------------------------------------------
    # ЛИЧНЫЙ КАНАЛ NOTIFICATIONS (§12.5)
    # ------------------------------------------------------------

    @api.model
    def _streams_get_notifications_channel(self, user=None, create=True):
        """Личный служебный канал уведомлений (§12.5). Ленивое создание.

        Канал заводится при первом полученном или отправленном уведомлении
        и по клику на иконку навбара — пустой канал в сайдбаре не нужен.
        Уникальность обеспечивает тот же частичный индекс, что и у Changes.
        """
        user = user or self.env.user
        if not user or not user.partner_id:
            return self.browse()
        channel = self.sudo().with_context(active_test=False).search([
            ('channel_kind', '=', 'notifications'),
            ('owner_user_id', '=', user.id),
        ], limit=1)
        if channel:
            if not channel.active:
                channel.write({'active': True})
            return channel
        if not create:
            return self.browse()
        channel = self.sudo().with_context(
            streams_sync=True, mail_create_nosubscribe=True).create({
                'name': 'Notifications',
                'channel_type': 'channel',
                'public': 'private',
                'channel_kind': 'notifications',
                'owner_user_id': user.id,
                'channel_last_seen_partner_ids': [
                    (0, 0, {'partner_id': user.partner_id.id})],
            })
        # ядровый `create` добавляет участником того, кто создаёт; уведомление
        # мог прислать кто угодно, а канал личный
        creator_partner = self.env.user.partner_id
        if creator_partner and creator_partner != user.partner_id:
            channel.sudo().with_context(
                streams_sync=True).channel_last_seen_partner_ids.filtered(
                    lambda member: member.partner_id == creator_partner
            ).unlink()
        _logger.info(
            'streams: создан личный канал Notifications %s для пользователя %s',
            channel.id, user.id)
        return channel

    def _streams_check_changes_owner(self):
        """Личную ленту читает только её владелец."""
        self.ensure_one()
        channel = self.sudo()
        if channel.channel_kind != 'changes' \
                or channel.owner_user_id != self.env.user:
            raise AccessError(_("This is not your Changes stream."))
        return channel

    # ------------------------------------------------------------
    # ЛЕНТА ИЗМЕНЕНИЙ (§8.2, §8.3, §8.4)
    # ------------------------------------------------------------

    def _streams_change_targets(self, limit=None, before_id=None):
        """Записи-источники канала, от самой свежей: [(model, res_id, last_id)].

        Группировка и сортировка делаются в SQL: элемент ленты — запись, а
        не сообщение, и «поднять наверх при новом изменении» (§8.3) — это
        сортировка по максимальному id сообщения.
        """
        self.ensure_one()
        self.env['mail.message'].flush()
        query = """
            SELECT msg.model AS model, msg.res_id AS res_id,
                   MAX(msg.id) AS last_id
              FROM %s rel
              JOIN mail_message msg ON msg.id = rel.message_id
             WHERE rel.channel_id = %%s
               AND msg.model IS NOT NULL
               AND msg.model != 'mail.channel'
               AND msg.res_id IS NOT NULL
             GROUP BY msg.model, msg.res_id
        """ % STREAM_REL_TABLE
        params = [self.id]
        if before_id:
            query += " HAVING MAX(msg.id) < %s"
            params.append(before_id)
        query += " ORDER BY last_id DESC"
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        self.env.cr.execute(query, params)
        return [
            (row['model'], row['res_id'], row['last_id'])
            for row in self.env.cr.dictfetchall()
        ]

    @api.model
    def _streams_readable_targets(self, targets):
        """Отсеять записи, к которым у пользователя нет доступа (§8.4).

        Проверка ретроактивная и на чтении: привязка сообщения к каналу в
        БД остаётся, но потерявший доступ ленту по этой записи не видит.
        Удалённые записи отсеиваются здесь же — `search` их не вернёт.
        """
        by_model = {}
        for res_model, res_id in targets:
            by_model.setdefault(res_model, set()).add(res_id)
        readable = set()
        for res_model, res_ids in by_model.items():
            if res_model not in self.env:
                continue
            model = self.env[res_model].sudo(False).with_context(
                active_test=False)
            if not model.check_access_rights('read', raise_exception=False):
                continue
            try:
                allowed = model.search([('id', 'in', list(res_ids))])
            except AccessError:
                continue
            readable.update((res_model, res_id) for res_id in allowed.ids)
        return readable

    def streams_changes_feed(self, limit=30, before_id=None):
        """Лента личного канала Changes (§8.3).

        Фильтрация по подписке и правам — серверная: клиенту нельзя
        отдавать `tracking_value` полей, на которые пользователь не
        подписан, и тем более записей, которые он читать не вправе.
        """
        channel = self._streams_check_changes_owner()
        targets = channel._streams_change_targets(
            limit=limit, before_id=before_id)
        if not targets:
            return []
        readable = self._streams_readable_targets(
            [(res_model, res_id) for res_model, res_id, _last in targets])
        targets = [
            target for target in targets if (target[0], target[1]) in readable
        ]
        if not targets:
            return []
        subscriptions = self.env['mail.field.subscription']._streams_find_by_targets(
            self._streams_targets_by_model(targets), user=self.env.user)
        subscribed_fields = {
            (subscription.res_model, subscription.res_id):
                set(subscription.field_ids.ids)
            for subscription in subscriptions
        }
        messages_by_target = channel._streams_change_messages(targets)
        member = self.env['mail.channel.partner'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', self.env.user.partner_id.id),
        ], limit=1)
        seen_message_id = member.seen_message_id.id or 0
        names = self._streams_target_names(targets)

        allowed_names_cache = {}
        result = []
        for res_model, res_id, last_id in targets:
            field_ids = subscribed_fields.get((res_model, res_id))
            if not field_ids:
                # подписки больше нет — показывать нечего
                continue
            if res_model not in allowed_names_cache:
                allowed_names_cache[res_model] = self.env[
                    'mail.field.subscription']._streams_accessible_field_names(
                        res_model)
            allowed_names = allowed_names_cache[res_model]
            changes = []
            for message in messages_by_target.get((res_model, res_id), []):
                values = [
                    {
                        'field_id': value.field.id,
                        'field_name': value.field.name,
                        'field_desc': value.field_desc,
                        'old': value.get_display_value('old')[0],
                        'new': value.get_display_value('new')[0],
                    }
                    for value in message.tracking_value_ids
                    if value.field.id in field_ids
                    and value.field.name in allowed_names
                ]
                if not values:
                    # после фильтрации по подписке показывать нечего
                    continue
                changes.append({
                    'message_id': message.id,
                    'date': fields.Datetime.to_string(message.date),
                    'author': message.author_id.display_name or '',
                    'author_id': message.author_id.id,
                    'values': values,
                })
            if not changes:
                continue
            result.append({
                'res_model': res_model,
                'res_id': res_id,
                'record_name': names.get((res_model, res_id)) or '',
                'last_message_id': last_id,
                'unread': last_id > seen_message_id,
                'changes': changes,
            })
        return result

    @api.model
    def _streams_targets_by_model(self, targets):
        by_model = {}
        for res_model, res_id, _last_id in targets:
            by_model.setdefault(res_model, set()).add(res_id)
        return by_model

    def _streams_change_messages(self, targets):
        """Сообщения канала по записям-источникам, свежие сверху."""
        self.ensure_one()
        domain = expression.AND([
            [('stream_channel_ids', 'in', self.ids)],
            expression.OR([
                ['&', ('model', '=', res_model), ('res_id', 'in', list(res_ids))]
                for res_model, res_ids in
                self._streams_targets_by_model(targets).items()
            ]),
        ])
        messages = self.env['mail.message'].sudo().search(
            domain, order='id DESC')
        grouped = {}
        for message in messages:
            key = (message.model, message.res_id)
            bucket = grouped.setdefault(key, [])
            if len(bucket) < STREAMS_CHANGES_PER_RECORD:
                bucket.append(message)
        return grouped

    def _streams_target_names(self, targets):
        """Имена записей-источников; читаем от лица пользователя."""
        names = {}
        for res_model, res_ids in self._streams_targets_by_model(
                targets).items():
            if res_model not in self.env:
                continue
            records = self.env[res_model].sudo(False).with_context(
                active_test=False).browse(list(res_ids)).exists()
            try:
                for res_id, name in records.name_get():
                    names[(res_model, res_id)] = name
            except AccessError:
                continue
        return names

    # ------------------------------------------------------------
    # ВЫДАЧА КЛИЕНТУ (§6, §11.3)
    # ------------------------------------------------------------

    def channel_info(self):
        """Клиенту нужен вид канала, его запись и фильтры участника."""
        channel_infos = super().channel_info()
        channels = {channel.id: channel for channel in self}
        member_by_channel = {}
        if self.env.user and self.env.user.partner_id:
            members = self.env['mail.channel.partner'].sudo().search([
                ('channel_id', 'in', self.ids),
                ('partner_id', '=', self.env.user.partner_id.id),
            ])
            member_by_channel = {
                member.channel_id.id: member for member in members}
        for info in channel_infos:
            channel = channels.get(info['id'])
            if not channel:
                continue
            info['channel_kind'] = channel.channel_kind or False
            info['res_model'] = channel.res_model or False
            info['res_id'] = channel.res_id or False
            member = member_by_channel.get(channel.id)
            if member:
                info['streams_filters'] = member._streams_get_filters()
        return channel_infos

    def streams_set_filters(self, filters):
        """Сохранить фильтры отображения текущего пользователя (§6)."""
        self.ensure_one()
        partner = self.env.user.partner_id
        if not partner:
            return False
        member = self.env['mail.channel.partner'].sudo().search([
            ('channel_id', '=', self.id),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if not member:
            return False
        return member._streams_set_filters(filters)

    # ------------------------------------------------------------
    # ПУБЛИКАЦИЯ И УЧАСТНИКИ
    # ------------------------------------------------------------

    def add_members(self, partner_ids=None, guest_ids=None,
                    invite_to_rtc_call=False):
        """В каналах записей нет служебных «joined/invited».

        Ядро постит по сообщению на каждого нового участника. Для канала
        записи это шум: участники приходят из followers, а лента канала —
        это лента документа.
        """
        record_channels = self.filtered(
            lambda channel: channel.channel_kind == 'record')
        other_channels = self - record_channels
        result = None
        if record_channels:
            result = super(
                MailChannel,
                record_channels.with_context(
                    streams_skip_join_notification=True),
            ).add_members(
                partner_ids=partner_ids, guest_ids=guest_ids,
                invite_to_rtc_call=invite_to_rtc_call)
        if other_channels:
            result = super(MailChannel, other_channels).add_members(
                partner_ids=partner_ids, guest_ids=guest_ids,
                invite_to_rtc_call=invite_to_rtc_call)
        return result

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        """Сообщение из канала записи пишется на саму запись (§11.2).

        Канал и чаттер — две проекции одного набора сообщений, поэтому
        отправленное из Discuss должно попасть и в чаттер документа.
        Проекция обратно в канал и рассылка по шине происходят в
        `mail.thread._message_post_after_hook`.
        """
        if self.env.context.get('streams_skip_join_notification') \
                and kwargs.get('message_type') == 'notification':
            return self.env['mail.message']
        if not self.env.context.get('streams_reverse_post') \
                and len(self) == 1 and self.channel_kind == 'record' \
                and self.res_model and self.res_id \
                and kwargs.get('message_type') in ('comment', 'email') \
                and self.res_model in self.env:
            record = self.env[self.res_model].with_context(
                active_test=False).browse(self.res_id).exists()
            if record:
                # Контроллер /mail/message/post приходит сюда под sudo, а
                # членство в канале не гарантирует прав на запись (§5.4):
                # участник, потерявший доступ по ir.rule, не должен писать
                # в её чаттер. Проверяем чтение реальным пользователем.
                as_user = record.with_user(self.env.user)
                as_user.check_access_rights('read')
                as_user.check_access_rule('read')
                return record.with_context(
                    streams_reverse_post=True).message_post(**kwargs)
        return super().message_post(**kwargs)

    # ------------------------------------------------------------
    # ДОМЕН ЛЕНТЫ КАНАЛА
    # ------------------------------------------------------------

    def _streams_message_domain(self):
        """Сообщения канала: собственные плюс проекции записей."""
        return expression.OR([
            ['&', ('model', '=', 'mail.channel'), ('res_id', 'in', self.ids)],
            [('stream_channel_ids', 'in', self.ids)],
        ])

    def _channel_fetch_message(self, last_id=False, limit=20):
        self.ensure_one()
        domain = self._streams_message_domain()
        if last_id:
            domain = expression.AND([domain, [('id', '<', last_id)]])
        return self.env['mail.message']._message_fetch(
            domain=domain, limit=limit)

    def _channel_seen(self, last_message_id=None):
        """Как в ядре, но последнее сообщение ищется и среди проекций."""
        self.ensure_one()
        domain = self._streams_message_domain()
        if last_message_id:
            domain = expression.AND([domain, [('id', '<=', last_message_id)]])
        last_message = self.env['mail.message'].search(
            domain, order="id DESC", limit=1)
        if not last_message:
            return
        self._set_last_seen_message(last_message)
        data = {
            'channel_id': self.id,
            'last_message_id': last_message.id,
            'partner_id': self.env.user.partner_id.id,
        }
        target = self if self.channel_type == 'chat' else self.env.user.partner_id
        self.env['bus.bus']._sendone(target, 'mail.channel.partner/seen', data)
        return last_message.id

    def _channel_last_message_ids(self):
        """Последнее сообщение канала с учётом проекций."""
        if not self:
            return []
        self.flush()
        self.env['mail.message'].flush()
        self.env.cr.execute(
            """
            SELECT channel_id AS id, MAX(message_id) AS message_id
              FROM (
                    SELECT res_id AS channel_id, id AS message_id
                      FROM mail_message
                     WHERE model = 'mail.channel' AND res_id IN %%s
                     UNION ALL
                    SELECT rel.channel_id, rel.message_id
                      FROM %s rel
                     WHERE rel.channel_id IN %%s
                   ) AS channel_messages
             GROUP BY channel_id
            """ % STREAM_REL_TABLE,
            (tuple(self.ids), tuple(self.ids)))
        return self.env.cr.dictfetchall()

    # ------------------------------------------------------------
    # НЕПРОЧИТАННОЕ (§5.7)
    # ------------------------------------------------------------

    def _compute_message_unread(self):
        """Счётчик непрочитанного; правила зависят от вида канала.

        В канале ЗАПИСИ изменения полей на счётчик не влияют (§5.7), в
        личном канале Changes они наоборот единственный его источник, а
        считаются там записи, а не сообщения (§8.3). В канале Notifications
        сообщений не бывает вовсе — счётчик берётся из уведомлений (§12.5).
        """
        changes_channels = self.filtered(
            lambda channel: channel.channel_kind == 'changes')
        if changes_channels:
            changes_channels._streams_compute_changes_unread()
        notify_channels = self.filtered(
            lambda channel: channel.channel_kind == 'notifications')
        if notify_channels:
            notify_channels._streams_compute_notify_unread()
        record_channels = self - changes_channels - notify_channels
        if record_channels:
            record_channels._streams_compute_record_unread()

    def _streams_compute_notify_unread(self):
        """Непрочитанное канала Notifications = непрочитанные уведомления."""
        counter = self.env['mail.notify']._streams_notify_counter()
        for channel in self:
            own = channel.sudo().owner_user_id == self.env.user
            channel.message_unread_counter = counter if own else 0
            channel.message_unread = bool(channel.message_unread_counter)

    def _streams_compute_changes_unread(self):
        """Непрочитанное личного канала Changes: число записей (§8.3).

        Права проверяются здесь же: запись, доступ к которой потерян,
        исчезает и из ленты, и из счётчика (§8.4). SQL этого не умеет,
        поэтому пары «модель+запись» отбираются запросом, а фильтрация
        по `ir.rule` идёт по одному `search` на модель.
        """
        partner_id = self.env.user.partner_id.id
        for channel in self:
            counter = 0
            if channel.id and partner_id:
                targets = channel._streams_unread_change_targets(partner_id)
                if targets:
                    counter = len(self._streams_readable_targets(targets))
            channel.message_unread_counter = counter
            channel.message_unread = bool(counter)

    def _streams_unread_change_targets(self, partner_id):
        """Записи с непрочитанными изменениями: [(model, res_id), ...]."""
        self.ensure_one()
        self.flush()
        self.env['mail.message'].flush()
        self.env.cr.execute(
            """
            SELECT DISTINCT msg.model AS model, msg.res_id AS res_id
              FROM mail_channel_partner cp
              JOIN %s rel ON rel.channel_id = cp.channel_id
              JOIN mail_message msg ON msg.id = rel.message_id
             WHERE cp.channel_id = %%s
               AND cp.partner_id = %%s
               AND (cp.seen_message_id IS NULL OR cp.seen_message_id < msg.id)
               AND msg.model IS NOT NULL
               AND msg.model != 'mail.channel'
               AND msg.res_id IS NOT NULL
            """ % STREAM_REL_TABLE,
            (self.id, partner_id))
        return [
            (row['model'], row['res_id'])
            for row in self.env.cr.dictfetchall()
        ]

    def _streams_compute_record_unread(self):
        """Счётчик по сообщениям канала и проекциям, без изменений полей.

        Форк ядрового `mail.thread._compute_message_unread`: ядровый SQL
        знает только про `model='mail.channel'` и проекции не видит, а
        изменения (`change`) по §5.7 не должны влиять на счётчик.
        """
        partner_id = self.env.user.partner_id.id
        subtypes = self.env['mail.message']._streams_subtype_ids()
        change_subtype_id = subtypes.get(STREAM_CHANGE) or 0
        activity_subtype_id = subtypes.get(STREAM_ACTIVITY) or 0
        res = dict.fromkeys(self.ids, 0)
        if self.ids:
            self.flush()
            self.env['mail.message'].flush()
            self._cr.execute(
                """
                SELECT channel_id, count(*)
                  FROM (
                        SELECT cp.channel_id AS channel_id, msg.id AS message_id
                          FROM mail_channel_partner cp
                          JOIN mail_message msg
                            ON msg.model = 'mail.channel'
                           AND msg.res_id = cp.channel_id
                         WHERE cp.channel_id = ANY(%%s)
                           AND cp.partner_id = %%s
                           AND (cp.seen_message_id IS NULL
                                OR cp.seen_message_id < msg.id)
                           AND msg.message_type NOT IN
                               ('notification', 'user_notification')
                           AND (msg.author_id IS NULL OR msg.author_id != %%s)
                           AND (msg.subtype_id IS NULL
                                OR msg.subtype_id != %%s)
                         UNION
                        SELECT cp.channel_id AS channel_id, msg.id AS message_id
                          FROM mail_channel_partner cp
                          JOIN %s rel ON rel.channel_id = cp.channel_id
                          JOIN mail_message msg ON msg.id = rel.message_id
                         WHERE cp.channel_id = ANY(%%s)
                           AND cp.partner_id = %%s
                           AND (cp.seen_message_id IS NULL
                                OR cp.seen_message_id < msg.id)
                           AND msg.message_type != 'user_notification'
                           AND (msg.author_id IS NULL OR msg.author_id != %%s)
                           AND (msg.subtype_id IS NULL
                                OR msg.subtype_id != %%s)
                           AND (msg.message_type != 'notification'
                                OR msg.subtype_id = %%s)
                       ) AS unread_messages
                 GROUP BY channel_id
                """ % STREAM_REL_TABLE,
                (list(self.ids), partner_id, partner_id, change_subtype_id,
                 list(self.ids), partner_id, partner_id, change_subtype_id,
                 activity_subtype_id))
            for channel_id, counter in self._cr.fetchall():
                res[channel_id] = counter

        for record in self:
            record.message_unread_counter = res.get(record._origin.id, 0)
            record.message_unread = bool(record.message_unread_counter)
