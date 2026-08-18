# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# Потоки сообщений (§2 ТЗ). False означает «прочее»: системное сообщение,
# которое не принадлежит ни одному потоку и канал записи не заводит.
STREAM_NOTE = 'note'
STREAM_COMMENT = 'comment'
STREAM_MESSAGE = 'message'
STREAM_CHANGE = 'change'
STREAM_ACTIVITY = 'activity'

# Потоки, первое сообщение которых заводит канал записи (§5.1).
STREAM_CHANNEL_TRIGGERS = (
    STREAM_COMMENT, STREAM_NOTE, STREAM_MESSAGE, STREAM_ACTIVITY)

# Таблица связи «сообщение ↔ канал». Имя нужно и Python-коду, и сырому SQL
# массовой привязки истории, поэтому вынесено в константу.
STREAM_REL_TABLE = 'mail_message_stream_channel_rel'

# Фильтры отображения канала записи (§6). Это настройка рендера, а не
# подписка: лента канала грузится целиком, скрытие происходит на клиенте.
STREAMS_FILTER_DEFAULTS = {
    STREAM_COMMENT: True,
    STREAM_NOTE: True,
    STREAM_MESSAGE: True,
    STREAM_CHANGE: False,
    STREAM_ACTIVITY: True,
}


class MailMessage(models.Model):
    """Проекция сообщения в каналы.

    Чаттер записи и канал записи — две проекции одного набора
    `mail.message`, а не два хранилища: сообщение пишется один раз и
    связывается с каналами через `stream_channel_ids`.
    """
    _inherit = 'mail.message'

    stream_channel_ids = fields.Many2many(
        'mail.channel', STREAM_REL_TABLE, 'message_id', 'channel_id',
        string='Stream Channels', copy=False)

    @api.model_create_multi
    def create(self, values_list):
        messages = super().create(values_list)
        messages._streams_link_existing_channels()
        messages._streams_route_field_subscriptions()
        return messages

    # ------------------------------------------------------------
    # КЛАССИФИКАЦИЯ
    # ------------------------------------------------------------

    @api.model
    def _streams_subtype_ids(self):
        """id подтипов, участвующих в классификации.

        `_xmlid_to_res_id` закэширован ormcache, поэтому вызов дешёвый и
        отдельный кэш не нужен.
        """
        xmlid_to_res_id = self.env['ir.model.data']._xmlid_to_res_id
        return {
            STREAM_CHANGE: xmlid_to_res_id(
                'streams.mt_change', raise_if_not_found=False),
            STREAM_ACTIVITY: xmlid_to_res_id(
                'streams.mt_activity', raise_if_not_found=False),
            STREAM_MESSAGE: xmlid_to_res_id(
                'streams.mt_message', raise_if_not_found=False),
            STREAM_NOTE: xmlid_to_res_id(
                'mail.mt_note', raise_if_not_found=False),
            STREAM_COMMENT: xmlid_to_res_id(
                'mail.mt_comment', raise_if_not_found=False),
        }

    @api.model
    def _streams_classify_vals(self, subtype_id, message_type):
        """Поток по подтипу и типу сообщения.

        Порядок проверок важен:

        * `user_notification` — адресное служебное уведомление, к потокам
          записи отношения не имеет;
        * входящее/исходящее письмо (`message_type='email'`) — всегда
          внешняя переписка, даже если подтип у него comment;
        * `message_type='notification'` без нашего подтипа — системный
          автолог (создание записи, падение job, приглашение в канал):
          это «прочее», канал по нему не заводится.
        """
        if message_type == 'user_notification':
            return False
        if message_type == 'email':
            return STREAM_MESSAGE
        subtypes = self._streams_subtype_ids()
        if subtype_id:
            for stream in (STREAM_CHANGE, STREAM_ACTIVITY, STREAM_MESSAGE):
                if subtypes.get(stream) and subtype_id == subtypes[stream]:
                    return stream
        if message_type == 'notification':
            return False
        if subtype_id and subtype_id == subtypes.get(STREAM_NOTE):
            return STREAM_NOTE
        if subtype_id and subtype_id == subtypes.get(STREAM_COMMENT):
            return STREAM_COMMENT
        return False

    def _streams_classify(self):
        self.ensure_one()
        return self._streams_classify_vals(
            self.subtype_id.id, self.message_type)

    # ------------------------------------------------------------
    # ВИДИМОСТЬ ГОСТЯ (§9.4, А3)
    # ------------------------------------------------------------

    @api.model
    def _streams_guest_message_domain(self, participant):
        """Что видит внешний участник канала (§9.4).

        Единственное место, где описана видимость гостя. Домен зеркалит
        `_streams_classify_vals`: гостю отдаётся ровно то, что
        классификатор относит к `comment` или `message`. Считать
        классификатором построчно нельзя — это Python-фильтр по всей
        ленте, поэтому домен и классификатор сверяются обязательным
        тестом на матрице (подтип × message_type).

        Пустые сообщения и удалённые клиентом (переподтипленные в note)
        отсеиваются здесь же: note в домен не входит.
        """
        subtypes = self._streams_subtype_ids()
        comment_id = subtypes.get(STREAM_COMMENT) or 0
        message_id = subtypes.get(STREAM_MESSAGE) or 0
        return expression.AND([
            [
                ('stream_channel_ids', 'in', participant.sudo().channel_id.ids),
                ('date', '>=', participant.sudo().history_from),
            ],
            expression.OR([
                # входящее/исходящее письмо — всегда внешняя переписка
                [('message_type', '=', 'email')],
                expression.AND([
                    [('message_type', '!=', 'user_notification')],
                    expression.OR([
                        [('subtype_id', '=', message_id)],
                        expression.AND([
                            # notification без наших подтипов — «прочее»
                            # (в том числе якорь треда): гостю не видно
                            [('message_type', '!=', 'notification')],
                            [('subtype_id', '=', comment_id)],
                        ]),
                    ]),
                ]),
            ]),
        ])

    # ------------------------------------------------------------
    # ПРИВЯЗКА К КАНАЛАМ
    # ------------------------------------------------------------

    def _streams_link_existing_channels(self):
        """Подшить сообщения к уже существующим каналам записей.

        Создание канала здесь не происходит: `mail.message.create` — это
        общий путь для всего, включая `_message_log` (трекинг полей и
        автолог создания), а такие сообщения канал заводить не должны.
        Создание канала живёт в `mail.thread._message_post_after_hook`.
        """
        targets = {}
        for message in self:
            if not message.model or not message.res_id:
                continue
            if message.model == 'mail.channel':
                continue
            if message.message_type == 'user_notification':
                continue
            targets.setdefault(message.model, set()).add(message.res_id)
        if not targets:
            return
        domain = expression.OR([
            ['&', ('res_model', '=', res_model), ('res_id', 'in', list(ids))]
            for res_model, ids in targets.items()
        ])
        channels = self.env['mail.channel'].sudo().with_context(
            active_test=False).search(expression.AND([
                [('channel_kind', '=', 'record')], domain]))
        if not channels:
            return
        channel_by_target = {
            (channel.res_model, channel.res_id): channel.id
            for channel in channels
        }
        pairs = []
        for message in self:
            channel_id = channel_by_target.get((message.model, message.res_id))
            if channel_id:
                pairs.append((message.id, channel_id))
        if pairs:
            self.env['mail.channel']._streams_insert_links(pairs)
            self.invalidate_cache(
                fnames=['stream_channel_ids'], ids=self.ids)

    # ------------------------------------------------------------
    # МАРШРУТИЗАЦИЯ ИЗМЕНЕНИЙ В ЛИЧНЫЕ КАНАЛЫ (§8.2)
    # ------------------------------------------------------------

    def _streams_route_field_subscriptions(self):
        """Подшить change-сообщение к личным каналам подписчиков.

        Персональных копий сообщения не делается: одно сообщение на
        `write` линкуется со всеми каналами, а «кто какие поля видит»
        решается на выдаче ленты (§8.2). Автор изменения обрабатывается
        наравне со всеми (§8.2): собственная правка попадает в его же
        Changes, если он на это поле подписан.
        """
        candidates = self.sudo().filtered(
            lambda message: message.model and message.res_id
            and message.model != 'mail.channel'
            and message.message_type != 'user_notification'
            and message.tracking_value_ids)
        if not candidates:
            return
        targets = {}
        for message in candidates:
            targets.setdefault(message.model, set()).add(message.res_id)
        subscriptions = self.env[
            'mail.field.subscription']._streams_find_by_targets(targets)
        if not subscriptions:
            return
        by_target = {}
        for subscription in subscriptions:
            by_target.setdefault(
                (subscription.res_model, subscription.res_id), []
            ).append(subscription)
        channel_model = self.env['mail.channel']
        channel_by_user = {}
        pairs = []
        for message in candidates:
            matched = by_target.get((message.model, message.res_id))
            if not matched:
                continue
            changed_field_ids = set(message.tracking_value_ids.field.ids)
            if not changed_field_ids:
                continue
            for subscription in matched:
                if not (changed_field_ids & set(subscription.field_ids.ids)):
                    continue
                user = subscription.user_id
                channel_id = channel_by_user.get(user.id)
                if channel_id is None:
                    channel = channel_model._streams_get_changes_channel(user)
                    channel_id = channel.id if channel else False
                    channel_by_user[user.id] = channel_id
                if channel_id:
                    pairs.append((message.id, channel_id))
        if not pairs:
            return
        channel_model._streams_insert_links(pairs)
        self.invalidate_cache(fnames=['stream_channel_ids'], ids=self.ids)
        self._streams_notify_changes_channels(set(
            channel_id for _message_id, channel_id in pairs))

    @api.model
    def _streams_notify_changes_channels(self, channel_ids):
        """Сказать владельцу канала, что лента изменилась.

        Тело сообщения по шине не идёт намеренно: подписчик мог потерять
        доступ к записи (§8.4), а проверять это на каждом изменении
        дороже, чем дать клиенту перезапросить ленту, которая права уже
        учитывает.
        """
        if not channel_ids:
            return
        channels = self.env['mail.channel'].sudo().browse(list(channel_ids))
        notifications = [
            (channel.owner_user_id.partner_id, 'streams.changes/updated',
             {'id': channel.id})
            for channel in channels
            if channel.owner_user_id and channel.owner_user_id.partner_id
        ]
        if notifications:
            self.env['bus.bus'].sudo()._sendmany(notifications)

    # ------------------------------------------------------------
    # ФОРМАТ ДЛЯ КЛИЕНТА
    # ------------------------------------------------------------

    def _message_format(self, fnames, format_reply=True):
        """Заготовка для клиента фазы 1b: каналы сообщения и его поток."""
        values_list = super()._message_format(
            fnames, format_reply=format_reply)
        for values in values_list:
            message_sudo = self.browse(values['id']).sudo().with_prefetch(
                self.ids)
            values['stream_channel_ids'] = message_sudo.stream_channel_ids.ids
            values['streams_kind'] = message_sudo._streams_classify()
        return values_list
