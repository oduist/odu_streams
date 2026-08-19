# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.addons.mail.tools.discuss import Store
from odoo.fields import Domain
from odoo.tools.sql import SQL

from .streams_partner_source import STREAMS_PARTNER_VIEW

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

# Потоки, попадающие в виртуальную часть ленты партнёра (§18.4, Р7):
# виртуальные `change` и «прочее» в агрегат не идут.
STREAMS_PARTNER_STREAMS = (
    STREAM_COMMENT, STREAM_NOTE, STREAM_MESSAGE, STREAM_ACTIVITY)

# Over-fetch виртуальной ленты (Р4). Лимит в 19 применяется ДО ACL
# (`mail_message.py:345`), поэтому страница «сжимается» и её приходится
# добирать сдвигом курсора; потолок итераций удерживает стоимость.
STREAMS_PARTNER_OVERFETCH_FACTOR = 4
STREAMS_PARTNER_OVERFETCH_ITERATIONS = 5


class MailMessage(models.Model):
    """Проекция сообщения в каналы.

    Чаттер записи и канал записи — две проекции одного набора
    `mail.message`, а не два хранилища: сообщение пишется один раз и
    связывается с каналами через `stream_channel_ids`.
    """
    _inherit = 'mail.message'

    stream_channel_ids = fields.Many2many(
        'discuss.channel', STREAM_REL_TABLE, 'message_id', 'channel_id',
        string='Stream Channels', copy=False)

    @api.model_create_multi
    def create(self, values_list):
        self._streams_normalize_tracking_vals(values_list)
        messages = super().create(values_list)
        messages._streams_link_existing_channels()
        messages._streams_route_field_subscriptions()
        return messages

    @api.model
    def _streams_normalize_tracking_vals(self, values_list):
        """Схлопнутое сообщение трекинга получает подтип Change (§4.1, §8.2).

        В 15 эту роль выполнял override `_message_log`; в 19 у
        `_message_log_batch` подтип зашит (`mail.mt_note`), а модели с
        собственным `_track_subtype` постят изменение через `message_post`.
        `mail.message.create` — общая точка обоих путей: любое
        notification-сообщение с tracking-значениями и есть изменение.
        """
        change_id = self._streams_subtype_ids().get(STREAM_CHANGE)
        if not change_id:
            return
        for values in values_list:
            if values.get('tracking_value_ids') \
                    and values.get('message_type') == 'notification':
                values['subtype_id'] = change_id

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
        * входящее/исходящее письмо — всегда внешняя переписка, даже если
          подтип у него comment (в 19 у исходящих тип `email_outgoing`);
        * `message_type='notification'` без нашего подтипа — системный
          автолог (создание записи, падение job, приглашение в канал):
          это «прочее», канал по нему не заводится.
        """
        if message_type == 'user_notification':
            return False
        if message_type in ('email', 'email_outgoing'):
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
        return (
            Domain('stream_channel_ids', 'in',
                   participant.sudo().channel_id.ids)
            & Domain('date', '>=', participant.sudo().history_from)
            & (
                # входящее/исходящее письмо — всегда внешняя переписка
                Domain('message_type', 'in', ('email', 'email_outgoing'))
                | (
                    Domain('message_type', '!=', 'user_notification')
                    & (
                        Domain('subtype_id', '=', message_id)
                        | (
                            # notification без наших подтипов — «прочее»
                            # (в том числе якорь треда): гостю не видно
                            Domain('message_type', '!=', 'notification')
                            & Domain('subtype_id', '=', comment_id)
                        )
                    )
                )
            )
        )

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
            if message.model == 'discuss.channel':
                continue
            if message.message_type == 'user_notification':
                continue
            targets.setdefault(message.model, set()).add(message.res_id)
        if not targets:
            return
        domain = Domain.OR([
            Domain('res_model', '=', res_model) & Domain('res_id', 'in', list(ids))
            for res_model, ids in targets.items()
        ])
        channels = self.env['discuss.channel'].sudo().with_context(
            active_test=False).search(
                Domain('channel_kind', '=', 'record') & domain)
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
            self.env['discuss.channel']._streams_insert_links(pairs)
            self.invalidate_recordset(fnames=['stream_channel_ids'])

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
            and message.model != 'discuss.channel'
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
        channel_model = self.env['discuss.channel']
        channel_by_user = {}
        pairs = []
        for message in candidates:
            matched = by_target.get((message.model, message.res_id))
            if not matched:
                continue
            changed_field_ids = set(message.tracking_value_ids.field_id.ids)
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
        self.invalidate_recordset(fnames=['stream_channel_ids'])
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
        channels = self.env['discuss.channel'].sudo().browse(list(channel_ids))
        for channel in channels:
            partner = channel.owner_user_id.partner_id
            if partner:
                partner._bus_send('streams.changes/updated', {'id': channel.id})

    # ------------------------------------------------------------
    # ФИЛЬТРЫ ОТОБРАЖЕНИЯ КАК ДОМЕН (§6, решение Р1 фазы 8)
    # ------------------------------------------------------------

    @api.model
    def _streams_stream_domain(self, stream):
        """Домен «сообщение принадлежит потоку `stream`».

        Зеркало `_streams_classify_vals`, выраженное доменом: тот же
        порядок проверок, включая приоритет письма над подтипом.
        Классификатором построчно фильтровать нельзя — сервер отдаёт
        `limit` сообщений ДО фильтра, и питоновский фильтр поверх выдачи
        ломает пагинацию (риск 1 отчёта core). Совпадение домена и
        классификатора закрыто тестом на матрице (подтип × message_type).
        """
        subtypes = self._streams_subtype_ids()
        email_types = ('email', 'email_outgoing')
        is_email = Domain('message_type', 'in', email_types)
        not_email = Domain('message_type', 'not in', email_types)
        # адресное служебное уведомление к потокам записи не относится
        base = Domain('message_type', '!=', 'user_notification')
        if stream == STREAM_MESSAGE:
            return base & (
                is_email
                | (not_email
                   & Domain('subtype_id', '=',
                            subtypes.get(STREAM_MESSAGE) or 0)))
        if stream in (STREAM_CHANGE, STREAM_ACTIVITY):
            # письмо остаётся внешней перепиской даже с нашим подтипом
            return base & not_email & Domain(
                'subtype_id', '=', subtypes.get(stream) or 0)
        if stream in (STREAM_NOTE, STREAM_COMMENT):
            # notification без наших подтипов — «прочее», не note/comment
            return (base & not_email
                    & Domain('message_type', '!=', 'notification')
                    & Domain('subtype_id', '=', subtypes.get(stream) or 0))
        return Domain.FALSE

    @api.model
    def _streams_filters_domain(self, channel):
        """Минус потоки, выключенные участником в канале записи (§6).

        Сообщения без потока («прочее») ни в один поточный домен не
        попадают, поэтому видны всегда — как и в клиенте 15.
        """
        member = channel.sudo().self_member_id
        if not member:
            return Domain.TRUE
        domain = Domain.TRUE
        for stream, enabled in member._streams_get_filters().items():
            if not enabled:
                domain &= ~self._streams_stream_domain(stream)
        return domain

    # ------------------------------------------------------------
    # ВИРТУАЛЬНАЯ ЛЕНТА ПАРТНЁРА (§18)
    # ------------------------------------------------------------

    @api.model
    def _streams_partner_domain(self, partner):
        """Домен агрегированной ленты контакта или None (§18.2, §18.4).

        None означает «работать как раньше, лентой самой карточки»: так
        отдаётся охват Direct (Р6, Р12) и деградация при отсутствии вьюхи
        (Р10) — сломанная вьюха не должна ронять чаттер.

        Виртуальная часть ограничена потоками comment/note/message/
        activity: виртуальные `change` и «прочее» в агрегат не попадают
        (§18.4). Ветка самого партнёра ограничений не имеет — изменения
        по самому контакту показываются как раньше, по фильтру §6.

        `sudo()` здесь нет и быть не может: единственное, что закрывает
        сообщения недоступных записей, — ядровый `mail.message._search`
        с `_find_allowed_doc_ids`.
        """
        scope = self.env.user._streams_partner_scope()
        if scope == 'direct':
            return None
        source = self.env['streams.partner.source']
        if not source._streams_view_available():
            _logger.error(
                'streams: вьюха %s отсутствует — лента контакта %s'
                ' деградирует в Direct', STREAMS_PARTNER_VIEW, partner.id)
            return None
        if scope == 'company':
            column, target = (
                'commercial_partner_id', partner.commercial_partner_id.id)
        else:
            column, target = 'partner_id', partner.id
        if not target:
            return None
        virtual = Domain('id', 'in', SQL(
            'SELECT v.message_id FROM %(view)s v WHERE v.%(column)s = %(target)s',
            view=SQL.identifier(STREAMS_PARTNER_VIEW),
            column=SQL.identifier(column),
            target=target,
            to_flush=source._streams_flush_fields(),
        )) & Domain.OR([
            self._streams_stream_domain(stream)
            for stream in STREAMS_PARTNER_STREAMS
        ])
        direct = Domain('model', '=', 'res.partner') \
            & Domain('res_id', '=', partner.id)
        # ядровый терм теряется вместе с thread — возвращаем его явно
        return (direct | virtual) \
            & Domain('message_type', '!=', 'user_notification')

    def _streams_partner_page(self, domain, *, search_term, is_notification,
                              before, after, around, limit):
        """Страница виртуальной ленты с добором после ACL (Р4).

        Ядро применяет `limit` в SQL ДО фильтрации прав
        (`mail_message.py:345`), а в ленте контакта прав режет много:
        пользователь видит карточку, но не видит половину её заказов.
        Поэтому страница набирается итеративным сдвигом курсора тем же
        доменом и по монотонно убывающему (растущему при `after`) id —
        пагинация клиента при этом остаётся корректной.

        Пустая выборка курсор двигать не даёт (нижняя граница окна
        известна только SQL), поэтому окно расширяется от той же точки.
        `around` добора не имеет: это разовый переход к сообщению, а не
        прокрутка ленты.
        """
        fetch = lambda cursor, page_limit: super(  # noqa: E731
            MailMessage, self)._message_fetch(
                domain, thread=None, search_term=search_term,
                is_notification=is_notification,
                before=None if after else cursor,
                after=cursor if after else None,
                around=around, limit=page_limit)
        if around is not None:
            return fetch(None, limit)
        ascending = bool(after)
        cursor = after if ascending else before
        page_limit = limit * STREAMS_PARTNER_OVERFETCH_FACTOR
        result = None
        collected = []
        seen = set()
        for _iteration in range(STREAMS_PARTNER_OVERFETCH_ITERATIONS):
            page = fetch(cursor, page_limit)
            if result is None:
                # `count` и прочие ключи считаются по всему домену —
                # берём их из первой выборки
                result = page
            page_ids = page['messages'].ids
            if not page_ids:
                page_limit *= 2
                continue
            for message_id in page_ids:
                if message_id not in seen:
                    seen.add(message_id)
                    collected.append(message_id)
            if len(collected) >= limit:
                break
            cursor = max(page_ids) if ascending else min(page_ids)
        collected.sort(reverse=not ascending)
        result['messages'] = self.browse(sorted(collected[:limit],
                                                reverse=True))
        return result

    # ------------------------------------------------------------
    # ЛЕНТА КАНАЛА С ПРОЕКЦИЯМИ
    # ------------------------------------------------------------

    def _message_fetch(self, domain, *, thread=None, search_term=None,
                       is_notification=None, before=None, after=None,
                       around=None, limit=30):
        """Лента канала записи — собственные сообщения плюс проекции.

        Ядровый fetch жёстко зашивает `model/res_id` треда; для наших
        каналов тред разворачивается в домен проекций, дальше работает
        ядровая пагинация.

        Здесь же применяются фильтры потоков участника (§6): решение Р1
        фазы 8 — фильтрация серверная, клиент рисует тумблеры и
        перечитывает ленту. Контекст `streams_unfiltered=True` отключает
        фильтр (мобильное API фильтрует у себя на клиенте, его контракт
        меняться не должен).

        Чаттер `res.partner` — вторая ветка (§18): тред разворачивается в
        домен агрегата, дальше работает ядровая пагинация с добором
        страницы после ACL.
        """
        if thread is not None and thread._name == 'res.partner' \
                and len(thread) == 1:
            partner_domain = self._streams_partner_domain(thread)
            if partner_domain is not None:
                domain = partner_domain if domain is None \
                    else Domain(domain) & partner_domain
                return self._streams_partner_page(
                    domain, search_term=search_term,
                    is_notification=is_notification, before=before,
                    after=after, around=around, limit=limit)
        if thread is not None and thread._name == 'discuss.channel' \
                and len(thread) == 1 and thread.channel_kind:
            projection = thread._streams_message_domain() \
                & Domain('message_type', '!=', 'user_notification')
            if thread.channel_kind == 'record' \
                    and not self.env.context.get('streams_unfiltered'):
                projection &= self._streams_filters_domain(thread)
            domain = projection if domain is None \
                else Domain(domain) & projection
            thread = None
        return super()._message_fetch(
            domain, thread=thread, search_term=search_term,
            is_notification=is_notification, before=before, after=after,
            around=around, limit=limit)

    # ------------------------------------------------------------
    # ФОРМАТ ДЛЯ КЛИЕНТА
    # ------------------------------------------------------------

    def _to_store_defaults(self, target):
        """Клиенту нужны каналы сообщения и его поток."""
        return super()._to_store_defaults(target) + [
            Store.Attr(
                'stream_channel_ids',
                value=lambda message: message.sudo().stream_channel_ids.ids),
            Store.Attr(
                'streams_kind',
                value=lambda message: message.sudo()._streams_classify()),
        ]
