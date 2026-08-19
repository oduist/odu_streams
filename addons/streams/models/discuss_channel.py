# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.fields import Domain

from .mail_message import (
    STREAMS_FILTER_DEFAULTS, STREAM_REL_TABLE)

# Сколько изменений на запись отдаётся в ленту Changes за один запрос.
# Лента — сводка «что поменялось», а не полная история записи.
STREAMS_CHANGES_PER_RECORD = 20

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    """Канал записи: групповое обсуждение конкретной записи (§3, §5)."""
    _inherit = 'discuss.channel'

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

    _streams_record_idx = models.Index("(res_model, res_id)")
    # Уникальность канала записи. Частичный индекс, а не Constraint: обычные
    # каналы Discuss не имеют res_model/res_id и под ограничение попадать
    # не должны.
    _streams_record_uniq = models.UniqueIndex(
        "(res_model, res_id) WHERE channel_kind = 'record'")
    # Личный служебный канал у пользователя ровно один на вид (§8.3, §12.5):
    # гонка двух параллельных подписок не должна плодить дубли.
    _streams_owner_uniq = models.UniqueIndex(
        "(channel_kind, owner_user_id)"
        " WHERE channel_kind IN ('changes', 'notifications')"
        " AND owner_user_id IS NOT NULL")

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
        self.env['mail.message'].flush_model()
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
        messages.invalidate_recordset(fnames=['stream_channel_ids'])

    def _streams_attach_history(self):
        """Подшить к каналу всю прежнюю историю сообщений записи (§5.1)."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return
        self.env['mail.message'].flush_model()
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
        self.env['mail.message'].invalidate_model(
            fnames=['stream_channel_ids'])

    def _streams_merge_into(self, target):
        """Слить канал-источник в канал получателя (§5.6).

        Сообщения перелинковываются, участники объединяются, источник
        архивируется. Дубли связей снимаем до UPDATE: первичный ключ
        m2m-таблицы иначе не даст перенести пересечение.
        """
        self.ensure_one()
        target.ensure_one()
        self.env['mail.message'].flush_model()
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
        self.env['mail.message'].invalidate_model(
            fnames=['stream_channel_ids'])
        partner_ids = (self.channel_partner_ids - target.channel_partner_ids).ids
        if partner_ids:
            target.sudo().with_context(streams_sync=True).add_members(
                partner_ids=partner_ids)
        self.sudo().write({'active': False})
        _logger.info(
            'streams: канал %s слит в канал %s', self.id, target.id)

    # ------------------------------------------------------------
    # ЛИЧНЫЕ КАНАЛЫ (§8.3, §12.5)
    # ------------------------------------------------------------

    @api.model
    def _streams_get_personal_channel(self, kind, name, user, create=True):
        """Личный служебный канал пользователя; создаётся лениво.

        Канал заводится при первом реальном использовании, а не всем
        подряд: пустой канал в сайдбаре не нужен.
        """
        user = user or self.env.user
        if not user or not user.partner_id:
            return self.browse()
        channel = self.sudo().with_context(active_test=False).search([
            ('channel_kind', '=', kind),
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
                'name': name,
                'channel_type': 'channel',
                'channel_kind': kind,
                'owner_user_id': user.id,
                'channel_member_ids': [
                    (0, 0, {'partner_id': user.partner_id.id})],
            })
        # ядровый `create` всегда добавляет участником того, кто создаёт;
        # триггером мог быть кто угодно, а канал личный
        creator_partner = self.env.user.partner_id
        if creator_partner and creator_partner != user.partner_id:
            channel.sudo().channel_member_ids.filtered(
                lambda member: member.partner_id == creator_partner
            ).with_context(streams_sync=True).unlink()
        _logger.info(
            'streams: создан личный канал %s %s для пользователя %s',
            kind, channel.id, user.id)
        return channel

    @api.model
    def _streams_get_changes_channel(self, user=None, create=True):
        """Личный канал изменений пользователя (§8.3)."""
        return self._streams_get_personal_channel(
            'changes', 'Changes', user, create=create)

    @api.model
    def _streams_get_notifications_channel(self, user=None, create=True):
        """Личный служебный канал уведомлений (§12.5)."""
        return self._streams_get_personal_channel(
            'notifications', 'Notifications', user, create=create)

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
        self.env['mail.message'].flush_model()
        query = """
            SELECT msg.model AS model, msg.res_id AS res_id,
                   MAX(msg.id) AS last_id
              FROM %s rel
              JOIN mail_message msg ON msg.id = rel.message_id
             WHERE rel.channel_id = %%s
               AND msg.model IS NOT NULL
               AND msg.model != 'discuss.channel'
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
            if not model.has_access('read'):
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
        member = self.env['discuss.channel.member'].sudo().search([
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
                        'field_id': value.field_id.id,
                        'field_name': value.field_id.name,
                        'field_desc': value.field_id.field_description,
                        'old': value._format_display_value(
                            value.field_id.ttype, new=False)[0],
                        'new': value._format_display_value(
                            value.field_id.ttype, new=True)[0],
                    }
                    for value in message.tracking_value_ids
                    if value.field_id.id in field_ids
                    and value.field_id.name in allowed_names
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
        domain = Domain('stream_channel_ids', 'in', self.ids) & Domain.OR([
            Domain('model', '=', res_model) & Domain('res_id', 'in', list(res_ids))
            for res_model, res_ids in
            self._streams_targets_by_model(targets).items()
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
                for record in records:
                    names[(res_model, record.id)] = record.display_name
            except AccessError:
                continue
        return names

    # ------------------------------------------------------------
    # ВЫДАЧА КЛИЕНТУ (§6, §11.3)
    # ------------------------------------------------------------

    def _to_store_defaults(self, target):
        """Клиенту нужен вид канала, его запись и фильтры участника."""
        res = super()._to_store_defaults(target)
        res += ['channel_kind', 'res_model', 'res_id']
        if target.is_current_user(self.env):
            res.append(Store.Attr(
                'streams_filters',
                value=lambda channel: (
                    channel.self_member_id._streams_get_filters()
                    if channel.self_member_id
                    else dict(STREAMS_FILTER_DEFAULTS))))
        return res

    def streams_set_filters(self, filters):
        """Сохранить фильтры отображения текущего пользователя (§6)."""
        self.ensure_one()
        member = self._streams_self_member()
        if not member:
            return False
        return member._streams_set_filters(filters)

    # ------------------------------------------------------------
    # ПРОЧТЕНИЕ (решение Р4 фазы 8)
    # ------------------------------------------------------------

    def streams_mark_read(self, last_message_id):
        """Отметить канал прочитанным до указанного сообщения.

        Маршрута 15 `/mail/channel/set_last_seen_message` в 19 нет, а
        ядровый `/discuss/channel/mark_as_read` ничего не возвращает —
        лентам Changes и Notifications нужен свежий счётчик в ответе,
        иначе после доскролла бейдж в сайдбаре остаётся старым.

        Не участник — `False` без исключения: канал могли покинуть в
        параллельной вкладке, ронять доскролл из-за этого незачем.
        """
        self.ensure_one()
        last_message_id = int(last_message_id or 0)
        if not last_message_id:
            return False
        member = self._streams_self_member()
        if not member:
            return False
        # найти строку участника можно только через sudo (ACL на
        # discuss.channel.member узкий), но сама отметка прочтения —
        # бизнес-логика и идёт правами пользователя
        member = member.sudo(False)
        member._mark_as_read(last_message_id)
        member.invalidate_recordset(['message_unread_counter'])
        return {'unread': member.message_unread_counter}

    def _streams_self_member(self):
        """Участник канала для текущего пользователя (или пусто)."""
        self.ensure_one()
        partner = self.env.user.partner_id
        if not partner:
            return self.env['discuss.channel.member']
        return self.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', self.id),
            ('partner_id', '=', partner.id),
        ], limit=1)

    # ------------------------------------------------------------
    # ПУБЛИКАЦИЯ
    # ------------------------------------------------------------

    def message_post(self, *, message_type='notification', **kwargs):
        """Сообщение из канала записи пишется на саму запись (§11.2).

        Канал и чаттер — две проекции одного набора сообщений, поэтому
        отправленное из Discuss должно попасть и в чаттер документа.
        Проекция обратно в канал и рассылка по шине происходят в
        `mail.thread._message_post_after_hook`.
        """
        if not self.env.context.get('streams_reverse_post') \
                and len(self) == 1 and self.channel_kind == 'record' \
                and self.res_model and self.res_id \
                and message_type in ('comment', 'email') \
                and self.res_model in self.env:
            record = self.env[self.res_model].with_context(
                active_test=False).browse(self.res_id).exists()
            if record:
                # Членство в канале не гарантирует прав на запись (§5.4):
                # участник, потерявший доступ по ir.rule, не должен писать
                # в её чаттер. Проверяем чтение реальным пользователем.
                record.with_user(self.env.user).check_access('read')
                return record.with_context(
                    streams_reverse_post=True).message_post(
                        message_type=message_type, **kwargs)
        return super().message_post(message_type=message_type, **kwargs)

    # ------------------------------------------------------------
    # ДОМЕН ЛЕНТЫ КАНАЛА
    # ------------------------------------------------------------

    def _streams_message_domain(self):
        """Сообщения канала: собственные плюс проекции записей."""
        return (
            (Domain('model', '=', 'discuss.channel')
             & Domain('res_id', 'in', self.ids))
            | Domain('stream_channel_ids', 'in', self.ids)
        )

    def _get_last_messages(self):
        """Последнее сообщение канала с учётом проекций."""
        streams_channels = self.filtered('channel_kind')
        other_channels = self - streams_channels
        messages = super(DiscussChannel, other_channels)._get_last_messages() \
            if other_channels else self.env['mail.message']
        if not streams_channels:
            return messages
        self.env['mail.message'].flush_model()
        self.env.cr.execute(
            """
            SELECT MAX(message_id) AS message_id
              FROM (
                    SELECT res_id AS channel_id, id AS message_id
                      FROM mail_message
                     WHERE model = 'discuss.channel' AND res_id IN %%s
                     UNION ALL
                    SELECT rel.channel_id, rel.message_id
                      FROM %s rel
                     WHERE rel.channel_id IN %%s
                   ) AS channel_messages
             GROUP BY channel_id
            """ % STREAM_REL_TABLE,
            (tuple(streams_channels.ids), tuple(streams_channels.ids)))
        message_ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        return messages | self.env['mail.message'].browse(message_ids)
