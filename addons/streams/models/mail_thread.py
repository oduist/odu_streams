# -*- encoding: utf-8 -*-
import logging

from odoo import models, api
from odoo.exceptions import AccessError
from odoo.osv import expression

from .mail_message import (
    STREAM_CHANNEL_TRIGGERS, STREAM_COMMENT, STREAM_MESSAGE)

_logger = logging.getLogger(__name__)

# Модели, для которых канал записи не заводится ни при каких условиях.
# mail.channel — сам канал; connect_messagebox.message — по решению
# пользователя; mail.activity наследует mail.thread не везде, но на всякий
# случай перечислена явно.
STREAMS_MODEL_BLACKLIST = (
    'mail.channel',
    'connect_messagebox.message',
    'mail.activity',
    'mail.wizard.invite',
)


class MailThread(models.AbstractModel):
    """Серверное ядро потоков (§5, §7, §10 ТЗ).

    Три группы изменений:

    * автоподписка вырезана — followers только явные;
    * внутренним пользователям письма из записей не уходят;
    * запись лениво обзаводится каналом Discuss, участники которого
      двусторонне синхронизированы с followers.
    """
    _inherit = 'mail.thread'

    # ------------------------------------------------------------
    # ВЫРЕЗАНИЕ АВТОПОДПИСКИ (§10)
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Создание записи никого не подписывает.

        `mail_create_nosubscribe` гасит подписку текущего пользователя в
        ядровом `create`; контекст возвращаем исходный, чтобы флаг не
        протёк в дальнейшие вызовы на возвращённом recordset.
        """
        records = super(
            MailThread,
            self.with_context(mail_create_nosubscribe=True),
        ).create(vals_list)
        return records.with_env(self.env)

    def _message_auto_subscribe(self, updated_values, followers_existing_policy='skip'):
        """Автоподписка вырезана целиком (§10.1)."""
        return True

    def _message_auto_subscribe_notify(self, partner_ids, template):
        """Уведомления автоподписки вместе с ней и уходят."""
        return True

    # ------------------------------------------------------------
    # ЗАПРЕТ ПИСЕМ ВНУТРЕННИМ ПОЛЬЗОВАТЕЛЯМ (§7)
    # ------------------------------------------------------------

    def _notify_record_by_email(self, message, recipients_data, msg_vals=False, **kwargs):
        """Внутренние пользователи не получают писем из записей.

        Фильтруем по `type`, а не по `notif`: `mail.wizard.invite`
        вызывает этот метод напрямую с зашитым `notif='email'`, и по
        `notif` приглашение внутреннему сотруднику всё равно ушло бы
        письмом.
        """
        external = [
            recipient for recipient in recipients_data
            if recipient.get('type') != 'user'
        ]
        dropped = len(recipients_data) - len(external)
        if dropped:
            _logger.debug(
                'streams: письма подавлены для %s внутренних получателей '
                'сообщения %s', dropped, message.id)
        if not external:
            return True
        return super()._notify_record_by_email(
            message, external, msg_vals=msg_vals, **kwargs)

    # ------------------------------------------------------------
    # ПОДТИП ИЗМЕНЕНИЙ (§4.1, §8.2)
    # ------------------------------------------------------------

    def _message_log(self, **kwargs):
        """Схлопнутое сообщение трекинга получает подтип Change.

        `mail_extra_recipients` ставит на трекинг `mail_track_log_only`,
        поэтому ядро уводит изменения в `_message_log` с подтипом
        `mail.mt_note` — по нему изменение неотличимо от заметки.
        Подтип Change объявлен `default=False`, так что подписчиков у
        него нет и рассылки по-прежнему не происходит.
        """
        if kwargs.get('tracking_value_ids') and not kwargs.get('subtype_id'):
            subtype_id = self.env['ir.model.data']._xmlid_to_res_id(
                'streams.mt_change', raise_if_not_found=False)
            if subtype_id:
                kwargs['subtype_id'] = subtype_id
        return super()._message_log(**kwargs)

    # ------------------------------------------------------------
    # ПУБЛИКАЦИЯ СООБЩЕНИЯ
    # ------------------------------------------------------------

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        """Публикация сообщения не подписывает ни автора, ни получателей.

        `mail_post_autofollow` ставит композер чаттера из JS, поэтому
        убирать его надо из контекста, а не из аргументов.
        """
        context = self.env.context
        if context.get('mail_post_autofollow') or not context.get(
                'mail_create_nosubscribe'):
            new_context = {
                key: value for key, value in context.items()
                if key != 'mail_post_autofollow'
            }
            new_context['mail_create_nosubscribe'] = True
            self = self.with_context(new_context)
        return super().message_post(**kwargs)

    def _message_post_after_hook(self, message, msg_vals):
        """Ленивое создание канала записи и рассылка проекции (§5.1, §6).

        Хук вызывается ядром до `_notify_thread`, что и требуется:
        `_notify_thread` при пустых получателях выходит раньше, чем до
        нашего кода дошло бы дело.
        """
        result = super()._message_post_after_hook(message, msg_vals)
        try:
            self._streams_handle_posted_message(message, msg_vals)
        except Exception:
            # проекция в канал не должна ронять публикацию сообщения
            _logger.exception(
                'streams: не удалось спроецировать сообщение %s на %s,%s',
                message.id, self._name, self.id)
        return result

    def _streams_handle_posted_message(self, message, msg_vals=None):
        self.ensure_one()
        if not self._streams_channel_enabled():
            return self.env['mail.channel']
        msg_vals = msg_vals or {}
        stream = self.env['mail.message']._streams_classify_vals(
            msg_vals.get('subtype_id') or message.subtype_id.id,
            msg_vals.get('message_type') or message.message_type)
        if stream in (STREAM_COMMENT, STREAM_MESSAGE):
            # автор комментария/сообщения подписывается автоматически (§5.3):
            # написавший в обсуждение должен видеть ответы. Заметка (note)
            # не подписывает — это способ написать в канал, не подписываясь.
            # Внешних авторов отбрасывает фильтр внутренних в message_subscribe.
            self._streams_subscribe_author(message)
        channel = self._streams_find_channel()
        if not channel and stream in STREAM_CHANNEL_TRIGGERS:
            channel = self._streams_get_or_create_channel()
        if not channel:
            return self.env['mail.channel']
        if not channel.active:
            # новое сообщение в архивированной записи реанимирует канал (§5.5)
            channel.sudo().write({'active': True})
        channel._streams_link_messages(message)
        if stream == STREAM_MESSAGE:
            # ответ клиента (страницей или письмом) подписывает того, кто
            # выдал ему доступ (решение 6 от 2026-08-18) — до рассылки,
            # чтобы пригласивший получил проекцию по шине сразу
            self.env[
                'mail.channel.external.participant']._streams_subscribe_inviters(
                    channel, message.sudo().author_id)
        if stream:
            self._streams_broadcast(channel, message)
        return channel

    def _streams_subscribe_author(self, message):
        """Автоподписка автора comment/message (§5.3, решение 2026-08-18).

        Подписка происходит на каждом сообщении, а не только на первом:
        отвечающий в обсуждении подписывается так же, как начавший его.
        Идемпотентно: уже подписанный автор не трогается.
        """
        partner = message.sudo().author_id
        if not partner:
            return
        if partner in self.sudo().message_follower_ids.partner_id:
            return
        self.message_subscribe(partner_ids=[partner.id])

    def _check_can_update_message_content(self, message):
        """Гость правит своё сообщение в окне 2 минут (§9.4, А5).

        Общий гейт разрешает править только заметки, поэтому без этого
        override ядро отказало бы. Авторство и окно проверены контроллером
        до вызова — здесь только снимается ядровое ограничение.
        """
        if self.env.context.get('streams_guest_edit'):
            return
        return super()._check_can_update_message_content(message)

    # ------------------------------------------------------------
    # ПОДПИСКА НА ПОЛЯ (§8.1)
    # ------------------------------------------------------------

    def _streams_check_readable(self):
        """Подписка — операция над записью: без права чтения её нет."""
        self.ensure_one()
        self.check_access_rights('read')
        self.check_access_rule('read')

    def streams_get_field_subscription(self):
        """Состояние подписки текущего пользователя на поля записи.

        Отсутствие записи подписки — не «подписан на ничего»: диалог в
        этом случае показывает предзаполнение трекаемыми полями (§8.1),
        которое пользователь волен снять.
        """
        self._streams_check_readable()
        subscription_model = self.env['mail.field.subscription']
        available = subscription_model._streams_available_fields(self._name)
        subscription = subscription_model._streams_find(self._name, self.id)
        if subscription:
            selected = subscription.sudo().field_ids & available
            field_ids = selected.ids
        else:
            field_ids = available.filtered(lambda field: field.tracking).ids
        return {
            'res_model': self._name,
            'res_id': self.id,
            'subscribed': bool(subscription),
            'field_ids': field_ids,
            'available_fields': [
                {
                    'id': field.id,
                    'name': field.name,
                    'field_description': field.field_description,
                    'tracking': bool(field.tracking),
                }
                for field in available
            ],
        }

    def streams_set_field_subscription(self, field_ids):
        """Сохранить выбор пользователя; пустой список = отписка (§8.1)."""
        self._streams_check_readable()
        subscription_model = self.env['mail.field.subscription']
        # чужие/недоступные поля через RPC не протащить
        available = set(
            subscription_model._streams_available_fields(self._name).ids)
        field_ids = [
            field_id for field_id in (field_ids or []) if field_id in available
        ]
        subscription = subscription_model._streams_upsert(
            self._name, self.id, field_ids)
        if subscription:
            # личный канал заводится лениво — при первой подписке (§8.3)
            self.env['mail.channel']._streams_get_changes_channel(
                self.env.user)
        return {
            'res_model': self._name,
            'res_id': self.id,
            'subscribed': bool(subscription),
            'field_ids': subscription.sudo().field_ids.ids,
        }

    # ------------------------------------------------------------
    # КАНАЛ ЗАПИСИ
    # ------------------------------------------------------------

    def _streams_channel_enabled(self):
        """Может ли у этой модели быть канал записи."""
        if self._name in STREAMS_MODEL_BLACKLIST:
            return False
        if self._abstract or self._transient:
            return False
        return True

    def _streams_find_channel(self):
        """Канал записи, если он уже создан (в том числе архивированный)."""
        self.ensure_one()
        if not self._streams_channel_enabled() or not self.id:
            return self.env['mail.channel']
        return self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
            ], limit=1)

    def _streams_find_channels(self):
        """Каналы всех записей набора."""
        if not self.ids or not self._streams_channel_enabled():
            return self.env['mail.channel']
        return self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', self._name),
                ('res_id', 'in', self.ids),
            ])

    def _streams_channel_name(self):
        self.ensure_one()
        return self.sudo().display_name or '%s,%s' % (self._name, self.id)

    def _streams_get_or_create_channel(self):
        """Канал записи; создаётся вместе со всей историей сообщений."""
        self.ensure_one()
        channel = self._streams_find_channel()
        if channel:
            if not channel.active:
                channel.sudo().write({'active': True})
            return channel
        record = self.sudo()
        values = {
            'name': self._streams_channel_name(),
            'channel_type': 'channel',
            'public': 'private',
            'channel_kind': 'record',
            'res_model': self._name,
            'res_id': self.id,
        }
        if 'company_id' in self._fields:
            company = record.company_id
            values['company_id'] = company.id if company else False
        follower_partners = self._streams_follower_partners()
        if follower_partners:
            values['channel_last_seen_partner_ids'] = [
                (0, 0, {'partner_id': partner_id})
                for partner_id in follower_partners
            ]
        # streams_sync: зеркало «участник → follower» при создании не нужно —
        # участники и так копируются из followers, а создателя ядро добавляет
        # принудительно, и без guard'а он стал бы follower'ом записи
        channel = self.env['mail.channel'].sudo().with_context(
            streams_sync=True).create(values)
        # участники канала ≡ followers записи (§5.3): создателя, которого
        # ядровый create добавил сам, из участников убираем
        creator_partner = self.env.user.partner_id
        if creator_partner and creator_partner.id not in follower_partners:
            channel.sudo().with_context(
                streams_sync=True).channel_last_seen_partner_ids.filtered(
                    lambda member: member.partner_id == creator_partner
            ).unlink()
        channel._streams_attach_history()
        _logger.info(
            'streams: создан канал записи %s для %s,%s',
            channel.id, self._name, self.id)
        return channel

    def _streams_follower_partners(self):
        """Партнёры-followers записи, у которых есть внутренний пользователь."""
        self.ensure_one()
        partners = self.sudo().message_follower_ids.partner_id
        return [
            partner.id for partner in partners
            if partner.with_context(active_test=False).user_ids.filtered(
                lambda user: not user.share)
        ]

    # ------------------------------------------------------------
    # РАССЫЛКА ПРОЕКЦИЙ ПО ШИНЕ (§6)
    # ------------------------------------------------------------

    def _streams_broadcast(self, channel, message):
        """Разослать проекцию участникам, у которых есть доступ к записи.

        Ядро шлёт `mail.channel/new_message` на bus-канал самого
        `mail.channel`, то есть всем участникам без проверки прав. Тело
        сообщения записи участнику без доступа к записи отдавать нельзя,
        поэтому шлём адресно.
        """
        if not channel:
            return
        recipients = self._streams_readable_partners(
            channel.sudo().channel_partner_ids)
        if not recipients:
            return
        payload = message.sudo().message_format()[0]
        notifications = [
            (partner, 'mail.channel/new_message', {
                'id': channel.id,
                'message': dict(payload),
            })
            for partner in recipients
        ]
        self.env['bus.bus'].sudo()._sendmany(notifications)

    def _streams_readable_partners(self, partners):
        """Партнёры, чьи пользователи имеют доступ на чтение записи.

        Кэшировать ответ по набору групп нельзя: домен `ir.rule` вправе
        сослаться на самого пользователя («только мои записи»), и два
        сотрудника из одной группы получили бы одинаковый ответ там, где
        он различается. Зато кэшируется вычисленный домен: одинаковый
        домен — одинаковый ответ, и хватает одного запроса на каждый
        различный домен, а не на каждого участника.
        """
        self.ensure_one()
        readable = self.env['res.partner']
        if not partners:
            return readable
        rule_model = self.env['ir.rule']
        record_model = self.env[self._name].with_context(
            active_test=False).sudo()
        domain_cache = {}
        for partner in partners:
            user = partner.sudo().with_context(
                active_test=False).user_ids.filtered(
                    lambda item: item.active and not item.share)[:1]
            if not user:
                continue
            try:
                # ormcache, SQL не делает
                if not self.with_user(user).check_access_rights(
                        'read', raise_exception=False):
                    continue
                domain = rule_model.with_user(user)._compute_domain(
                    self._name, 'read')
            except AccessError:
                continue
            key = repr(domain)
            if key not in domain_cache:
                if not domain:
                    domain_cache[key] = True
                else:
                    domain_cache[key] = bool(record_model.search_count(
                        expression.AND([[('id', '=', self.id)], domain])))
            if domain_cache[key]:
                readable |= partner
        return readable

    # ------------------------------------------------------------
    # СИНХРОНИЗАЦИЯ FOLLOWERS ↔ УЧАСТНИКИ (§5.3)
    # ------------------------------------------------------------

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        """Подписывать можно только внутренних пользователей (§10.3)."""
        partner_ids = self._streams_filter_internal_partners(partner_ids)
        result = super().message_subscribe(
            partner_ids=partner_ids, subtype_ids=subtype_ids)
        if partner_ids and not self.env.context.get('streams_sync'):
            self._streams_mirror_members(partner_ids, add=True)
        return result

    def message_unsubscribe(self, partner_ids=None):
        result = super().message_unsubscribe(partner_ids=partner_ids)
        if partner_ids and not self.env.context.get('streams_sync'):
            self._streams_mirror_members(partner_ids, add=False)
        return result

    def _streams_filter_internal_partners(self, partner_ids):
        """Отбросить партнёров без внутреннего пользователя."""
        if not partner_ids:
            return partner_ids
        partners = self.env['res.partner'].sudo().browse(
            list(partner_ids)).exists()
        allowed = partners.filtered(
            lambda partner: partner.with_context(
                active_test=False).user_ids.filtered(
                    lambda user: not user.share))
        dropped = partners - allowed
        if dropped:
            _logger.debug(
                'streams: подписка отброшена для партнёров без внутреннего '
                'пользователя: %s', dropped.ids)
        return allowed.ids

    def _streams_mirror_members(self, partner_ids, add=True):
        """Отразить подписку в участниках уже существующего канала.

        Подписка канал не создаёт (§5.1): follower может появиться на
        записи, у которой обсуждения ещё не было.
        """
        channels = self._streams_find_channels()
        if not channels:
            return
        for channel in channels:
            channel_sudo = channel.sudo().with_context(streams_sync=True)
            if add:
                channel_sudo.add_members(partner_ids=list(partner_ids))
            else:
                channel_sudo._action_remove_members(
                    self.env['res.partner'].browse(list(partner_ids)))

    # ------------------------------------------------------------
    # ИМЯ, АРХИВАЦИЯ, СЛИЯНИЕ (§5.2, §5.5, §5.6)
    # ------------------------------------------------------------

    def _streams_name_trigger_fields(self):
        """Поля, изменение которых может поменять display_name.

        Надёжного хука на смену `display_name` в ядре нет: у большинства
        целевых моделей он не stored и `name_get` переопределён. Модели
        могут расширить список.
        """
        if self._rec_name and self._rec_name in self._fields:
            return [self._rec_name]
        return []

    def write(self, vals):
        result = super().write(vals)
        if self.ids and not self.env.context.get('streams_sync') \
                and self._streams_channel_enabled():
            triggers = set(self._streams_name_trigger_fields()) | {'active'}
            if triggers & set(vals):
                self._streams_sync_channels_after_write(vals)
        return result

    def _streams_sync_channels_after_write(self, vals):
        channels = self._streams_find_channels()
        if not channels:
            return
        channel_by_res_id = {channel.res_id: channel for channel in channels}
        for record in self:
            channel = channel_by_res_id.get(record.id)
            if not channel:
                continue
            channel_sudo = channel.sudo()
            if 'active' in vals:
                active = bool(vals.get('active'))
                if channel_sudo.active != active:
                    channel_sudo.write({'active': active})
            name = record._streams_channel_name()
            if name and channel_sudo.name != name:
                channel_sudo.channel_rename(name)

    def message_change_thread(self, new_thread, new_parent_message=False):
        """Слияние записей сливает и каналы (§5.6)."""
        source_channel = self._streams_find_channel()
        result = super().message_change_thread(
            new_thread, new_parent_message=new_parent_message)
        if source_channel and new_thread._streams_channel_enabled():
            target_channel = new_thread._streams_get_or_create_channel()
            if target_channel and target_channel != source_channel:
                source_channel._streams_merge_into(target_channel)
        return result
