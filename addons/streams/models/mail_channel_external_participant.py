# -*- encoding: utf-8 -*-
import logging
import secrets
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import consteq
from odoo.tools.mail import plaintext2html

_logger = logging.getLogger(__name__)

# Настройки продукта (§14, А9). get_param возвращает строку, поэтому все
# чтения идут через _streams_guest_param с int() и защитой от мусора.
GUEST_SESSION_DAYS_PARAM = 'streams.guest_session_days'
GUEST_POLL_INTERVAL_PARAM = 'streams.guest_poll_interval'
GUEST_EDIT_WINDOW_PARAM = 'streams.guest_edit_window'
GUEST_PRESENCE_TIMEOUT_PARAM = 'streams.guest_presence_timeout'
GUEST_MAX_UPLOAD_MB_PARAM = 'streams.guest_max_upload_mb'

DEFAULT_SESSION_DAYS = 7
DEFAULT_POLL_INTERVAL = 10
DEFAULT_EDIT_WINDOW = 120
DEFAULT_PRESENCE_TIMEOUT = 120
DEFAULT_MAX_UPLOAD_MB = 25

# Кука гостевой сессии (Р3): значение "<participant_id>|<session_token>",
# как у mail.guest, но с флагами и на собственном пути.
GUEST_COOKIE_NAME = 'sgsid'
GUEST_COOKIE_SEPARATOR = '|'
GUEST_COOKIE_PATH = '/streams'

# Heartbeat пишется не чаще раза в минуту (А2): десятисекундный поллинг
# иначе даёт 8 640 UPDATE в сутки на одного гостя.
TOUCH_INTERVAL = 60

# Лимиты гостевого ввода (А5)
MAX_GUEST_BODY = 10000
MAX_GUEST_ATTACHMENTS = 10

# Палитра реакций гостевой страницы (А5): произвольные строки не принимаем.
GUEST_REACTIONS = ('\U0001F44D', '\U0001F44E', '❤️',
                   '\U0001F600', '\U0001F62E', '\U0001F622', '\U0001F389')

# Префикс тела сообщения, удалённого клиентом (решение 4 от 2026-08-18).
GUEST_DELETED_PREFIX = 'Deleted by the customer:'


class MailChannelExternalParticipant(models.Model):
    """Внешний участник канала записи — гостевой доступ клиента (§9).

    Модель осознанно **не** `discuss.channel.member` и **не** `mail.guest`
    (Р1): строка участника канала немедленно уехала бы в followers записи
    через наше зеркало, а followers по §10.3 — только внутренние.
    Доступ гостя живёт только здесь, ядровые механики канала (channel_info,
    unread, seen, шина) остаются нетронутыми.

    Специфика ссылки вынесена в отдельные поля (поправка ТЗ): когда
    появится Telegram, участник будет тем же по смыслу, но с chat_id
    вместо токена — добавится значение `transport` и ветка в кроне.
    """
    _name = 'mail.channel.external.participant'
    _description = 'Channel External Participant'
    _rec_name = 'partner_id'
    _order = 'id desc'

    channel_id = fields.Many2one(
        'discuss.channel', string='Channel', required=True, index=True,
        ondelete='cascade')
    partner_id = fields.Many2one(
        'res.partner', string='Contact', required=True, index=True,
        ondelete='cascade',
        help="The individual contact invited to the chat, never a company.")
    transport = fields.Selection(
        [('link', 'Invitation link')], string='Transport',
        required=True, default='link',
        help="How this participant reaches the chat.")
    token = fields.Char(
        string='Invitation Token', copy=False, index=True,
        groups='base.group_system')
    token_date = fields.Datetime(
        string='Link Issued On', groups='base.group_system')
    history_from = fields.Datetime(
        string='Show History From', required=True,
        default=fields.Datetime.now,
        help="The participant sees comments and messages posted after this "
             "moment only.")
    session_token = fields.Char(
        string='Session Token', copy=False, index=True,
        groups='base.group_system')
    session_expiry = fields.Datetime(
        string='Session Expiry', groups='base.group_system')
    is_link_consumed = fields.Boolean(
        string='Link Used', default=False,
        help="The invitation link has already been exchanged for a session.")
    active = fields.Boolean(string='Active', default=True)
    last_seen = fields.Datetime(string='Last Seen')
    last_digest_sent = fields.Datetime(string='Last Digest Sent')
    anchor_message_id = fields.Many2one(
        'mail.message', string='Email Thread Anchor', ondelete='set null',
        help="Service message the invitation and digest emails reply to, so "
             "that answers by email are routed back to the record.")
    invited_by_id = fields.Many2one(
        'res.users', string='Invited By', ondelete='set null',
        default=lambda self: self.env.user)
    res_model = fields.Char(
        related='channel_id.res_model', string='Related Document Model',
        store=False)
    res_id = fields.Integer(
        related='channel_id.res_id', string='Related Document ID',
        store=False)
    link_url = fields.Char(
        string='Invitation Link', compute='_compute_link_url',
        groups='base.group_system')

    # Секреты уникальны глобально: поиск по токену идёт без канала.
    _token_uniq = models.UniqueIndex("(token) WHERE token IS NOT NULL")
    _session_uniq = models.UniqueIndex(
        "(session_token) WHERE session_token IS NOT NULL")
    # Повторное приглашение живого участника обновляет ту же строку;
    # отозванные строки остаются историей и под ограничение не попадают.
    _active_uniq = models.UniqueIndex("(channel_id, partner_id) WHERE active")

    # ------------------------------------------------------------
    # ОГРАНИЧЕНИЯ
    # ------------------------------------------------------------

    @api.constrains('channel_id')
    def _check_channel_kind(self):
        for participant in self:
            if participant.channel_id.channel_kind != 'record':
                raise ValidationError(
                    _("External participants can only be invited to a record "
                      "channel."))

    @api.constrains('partner_id')
    def _check_partner(self):
        for participant in self:
            partner = participant.partner_id
            if partner.is_company:
                raise ValidationError(
                    _("Invite an individual contact, not a company."))
            if partner.with_context(active_test=False).user_ids.filtered(
                    lambda user: not user.share):
                raise ValidationError(
                    _("%s is an internal user and cannot be invited as an "
                      "external participant.") % partner.display_name)

    def _compute_link_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url')
        for participant in self:
            token = participant.sudo().token
            participant.link_url = '%s/streams/guest/%s' % (
                base_url, token) if token else False

    # ------------------------------------------------------------
    # НАСТРОЙКИ (§14, А9)
    # ------------------------------------------------------------

    @api.model
    def _streams_guest_param(self, key, default):
        """Целочисленная настройка гостевого доступа.

        `get_param` возвращает строку, а в базе может лежать что угодно —
        мусор молча заменяем умолчанием, иначе гостевая страница упадёт
        на ровном месте.
        """
        value = self.env['ir.config_parameter'].sudo().get_param(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            _logger.warning(
                'streams: параметр %s содержит не число (%r), взято '
                'умолчание %s', key, value, default)
            return default
        return value if value > 0 else default

    @api.model
    def _streams_session_days(self):
        return self._streams_guest_param(
            GUEST_SESSION_DAYS_PARAM, DEFAULT_SESSION_DAYS)

    @api.model
    def _streams_poll_interval(self):
        return self._streams_guest_param(
            GUEST_POLL_INTERVAL_PARAM, DEFAULT_POLL_INTERVAL)

    @api.model
    def _streams_edit_window(self):
        return self._streams_guest_param(
            GUEST_EDIT_WINDOW_PARAM, DEFAULT_EDIT_WINDOW)

    @api.model
    def _streams_presence_timeout(self):
        return self._streams_guest_param(
            GUEST_PRESENCE_TIMEOUT_PARAM, DEFAULT_PRESENCE_TIMEOUT)

    @api.model
    def _streams_max_upload_bytes(self):
        return self._streams_guest_param(
            GUEST_MAX_UPLOAD_MB_PARAM, DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024

    # ------------------------------------------------------------
    # ТОКЕНЫ И СЕССИЯ (А2)
    # ------------------------------------------------------------

    @api.model
    def _streams_new_token(self):
        """256 бит из `secrets` — это не перебирается (Р14)."""
        return secrets.token_urlsafe(32)

    def _streams_issue_link(self):
        """Выдать новую одноразовую ссылку; возвращает абсолютный URL."""
        self.ensure_one()
        token = self._streams_new_token()
        self.sudo().write({
            'token': token,
            'token_date': fields.Datetime.now(),
            'is_link_consumed': False,
        })
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url')
        return '%s/streams/guest/%s' % (base_url, token)

    @api.model
    def _streams_from_token(self, token):
        """Участник по токену ссылки; сверка секрета — `consteq` (Р14)."""
        if not token or not isinstance(token, str):
            return self.browse()
        candidate = self.sudo().search(
            [('token', '=', token)], limit=1)
        if not candidate:
            return self.browse()
        if not candidate.token or not consteq(candidate.token, token):
            return self.browse()
        if not candidate._streams_is_usable():
            return self.browse()
        return candidate

    def _streams_is_usable(self):
        """Живой участник живого канала с существующим контактом."""
        self.ensure_one()
        participant = self.sudo()
        if not participant.active:
            return False
        channel = participant.channel_id
        if not channel or not channel.exists() or not channel.active:
            return False
        if not participant.partner_id or not participant.partner_id.exists():
            return False
        return True

    def _streams_open_session(self):
        """Обменять ссылку на сессию (§9.3). Возвращает значение куки.

        Ссылка гасится физически (`token = False`), а не флагом: утёкшая
        ссылка после этого не работает ни при каких обстоятельствах.
        """
        self.ensure_one()
        session_token = self._streams_new_token()
        now = fields.Datetime.now()
        self.sudo().write({
            'session_token': session_token,
            'session_expiry': now + timedelta(days=self._streams_session_days()),
            'is_link_consumed': True,
            'token': False,
            'last_seen': now,
        })
        _logger.info(
            'streams: гостевая сессия открыта для участника %s (канал %s)',
            self.id, self.sudo().channel_id.id)
        return '%s%s%s' % (self.id, GUEST_COOKIE_SEPARATOR, session_token)

    @api.model
    def _streams_from_session(self, cookie_value):
        """Участник по куке сессии; всё, что не сошлось, — пустой recordset."""
        if not cookie_value or not isinstance(cookie_value, str):
            return self.browse()
        parts = cookie_value.split(GUEST_COOKIE_SEPARATOR)
        if len(parts) != 2:
            return self.browse()
        raw_id, session_token = parts
        if not raw_id or not session_token:
            return self.browse()
        try:
            participant_id = int(raw_id)
        except (TypeError, ValueError):
            return self.browse()
        participant = self.sudo().with_context(
            active_test=False).browse(participant_id).exists()
        if not participant:
            return self.browse()
        if not participant.session_token or not consteq(
                participant.session_token, session_token):
            return self.browse()
        if not participant.session_expiry \
                or participant.session_expiry <= fields.Datetime.now():
            return self.browse()
        if not participant._streams_is_usable():
            return self.browse()
        return participant

    def _streams_touch(self, extend_session=True):
        """Сердцебиение присутствия (§9.5) и скользящее окно сессии.

        Пишем не чаще раза в минуту и продлеваем сессию, только когда до
        конца осталось меньше половины срока — иначе поллинг раз в десять
        секунд превращается в непрерывный UPDATE.
        """
        self.ensure_one()
        participant = self.sudo()
        now = fields.Datetime.now()
        values = {}
        if not participant.last_seen \
                or (now - participant.last_seen).total_seconds() >= TOUCH_INTERVAL:
            values['last_seen'] = now
        if extend_session and participant.session_expiry:
            days = self._streams_session_days()
            remaining = (participant.session_expiry - now).total_seconds()
            if remaining < days * 86400 / 2:
                values['session_expiry'] = now + timedelta(days=days)
        if values:
            participant.write(values)
        return bool(values)

    def _streams_revoke(self):
        """Отзыв доступа (§9.3): гаснут и ссылка, и сессия, и сам участник."""
        for participant in self:
            participant.sudo().write({
                'active': False,
                'token': False,
                'session_token': False,
                'session_expiry': False,
            })
            _logger.info(
                'streams: гостевой доступ участника %s отозван', participant.id)
        return True

    def action_revoke(self):
        """Кнопка Revoke в списке выданных доступов."""
        self._streams_revoke()
        return True

    def _streams_cookie_value(self):
        self.ensure_one()
        return '%s%s%s' % (
            self.id, GUEST_COOKIE_SEPARATOR, self.sudo().session_token)

    # ------------------------------------------------------------
    # ПРИГЛАШЕНИЕ (§9.2, А6)
    # ------------------------------------------------------------

    @api.model
    def _streams_get_or_create(self, channel, partner, history_from=None):
        """Upsert активного участника канала.

        Повторное приглашение того же контакта обновляет ту же строку
        (частичный UNIQUE по `(channel_id, partner_id) WHERE active`):
        два параллельных доступа у одного человека — это две ссылки, из
        которых одна всегда лишняя.
        """
        participant = self.sudo().with_context(active_test=True).search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', partner.id),
        ], limit=1)
        values = {}
        if history_from:
            values['history_from'] = history_from
        if participant:
            if values:
                participant.write(values)
            return participant
        values.update({
            'channel_id': channel.id,
            'partner_id': partner.id,
            'transport': 'link',
            'invited_by_id': self.env.user.id,
        })
        if not values.get('history_from'):
            values['history_from'] = fields.Datetime.now()
        return self.sudo().create(values)

    def _streams_get_or_create_anchor(self):
        """Якорь треда для ответа по email (Р10, §9.7).

        Служебное сообщение `message_type='notification'` с подтипом
        `mail.mt_comment`: по классификатору это «прочее» — канал не
        заводит, на unread не влияет, гостю не видно; при этом подтип не
        internal, поэтому ответ гостя ядро запостит нормальным
        `mt_comment`/`email`, а не заметкой.
        """
        self.ensure_one()
        participant = self.sudo()
        if participant.anchor_message_id and participant.anchor_message_id.exists():
            return participant.anchor_message_id
        channel = participant.channel_id
        # У канала якорь один на всех участников: тред записи общий.
        sibling = self.sudo().with_context(active_test=False).search([
            ('channel_id', '=', channel.id),
            ('anchor_message_id', '!=', False),
        ], limit=1)
        if sibling and sibling.anchor_message_id.exists():
            participant.write(
                {'anchor_message_id': sibling.anchor_message_id.id})
            return sibling.anchor_message_id
        record = participant._streams_record()
        if not record:
            return self.env['mail.message']
        anchor = record.sudo().message_post(
            body=_("External participant invited to the chat."),
            message_type='notification',
            subtype_xmlid='mail.mt_comment')
        participant.write({'anchor_message_id': anchor.id})
        return anchor

    def _streams_record(self):
        """Запись-источник канала."""
        self.ensure_one()
        channel = self.sudo().channel_id
        if not channel.res_model or not channel.res_id \
                or channel.res_model not in self.env:
            return None
        record = self.env[channel.res_model].sudo().with_context(
            active_test=False).browse(channel.res_id).exists()
        return record or None

    def _streams_reply_to(self):
        """Адрес для ответа гостя (§9.7).

        Без `mail.catchall.domain` ядро возвращает `default`, то есть
        ответить будет некуда — это состояние продукта, а не ошибка кода,
        поэтому предупреждаем в лог.
        """
        self.ensure_one()
        record = self._streams_record()
        if not record:
            return False
        reply_to = record._notify_get_reply_to(default=False)[record.id]
        if not reply_to:
            _logger.warning(
                'streams: guest replies cannot be routed — mail.catchall.domain '
                'is not configured (participant %s)', self.id)
            return False
        return reply_to

    def _streams_mail_values(self, link_url):
        """`email_values` письма гостю: адрес, нитка, ссылка."""
        self.ensure_one()
        participant = self.sudo()
        values = {
            'email_to': participant.partner_id.email,
            'auto_delete': False,
        }
        reply_to = participant._streams_reply_to()
        if reply_to:
            values['reply_to'] = reply_to
        anchor = participant.anchor_message_id
        if anchor and anchor.message_id:
            values['references'] = anchor.message_id
            values['headers'] = repr({'In-Reply-To': anchor.message_id})
        return values

    def _streams_send_template(self, template_xmlid, link_url,
                               force_send=False):
        """Отправить письмо гостю по шаблону (Р11).

        Дайджест и приглашение идут мимо `_notify_thread`: они не должны
        ни создавать `mail.message`, ни зависеть от followers.
        """
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning(
                'streams: шаблон письма %s не найден', template_xmlid)
            return self.env['mail.mail']
        email_values = self._streams_mail_values(link_url)
        if not email_values.get('email_to'):
            return self.env['mail.mail']
        mail_id = template.sudo().with_context(
            streams_guest_link=link_url).send_mail(
                self.id, force_send=force_send, raise_exception=False,
                email_values=email_values)
        return self.env['mail.mail'].sudo().browse(mail_id)

    # ------------------------------------------------------------
    # ЛЕНТА, ОТПРАВКА, ПРАВКА, УДАЛЕНИЕ, РЕАКЦИИ (А3, А5)
    # ------------------------------------------------------------
    #
    # Гейты живут здесь, а не в контроллере: контроллер занимается HTTP и
    # сериализацией, а «что гостю можно» должно быть в одном месте и под
    # тестом.

    def _streams_visible_domain(self):
        self.ensure_one()
        return self.env['mail.message']._streams_guest_message_domain(self)

    def _streams_visible_messages(self, after_id=None, before_id=None,
                                  limit=30):
        """Видимые гостю сообщения, снизу вверх."""
        self.ensure_one()
        domain = self._streams_visible_domain()
        if after_id:
            domain &= Domain('id', '>', int(after_id))
        if before_id:
            domain &= Domain('id', '<', int(before_id))
        messages = self.env['mail.message'].sudo().search(
            domain, order='id desc', limit=limit)
        return messages.sorted('id')

    def _streams_visible_message(self, message_id):
        """Одно сообщение, если оно вообще видно этому гостю."""
        self.ensure_one()
        try:
            message_id = int(message_id)
        except (TypeError, ValueError):
            return self.env['mail.message']
        domain = self._streams_visible_domain() \
            & Domain('id', '=', message_id)
        return self.env['mail.message'].sudo().search(domain, limit=1)

    def _streams_post_message(self, body, attachment_ids=None):
        """Сообщение гостя ложится на саму запись (§9.4, А5).

        `message_type='comment'` + подтип `streams.mt_message` даёт
        `streams_kind='message'`: сотрудникам это внешняя переписка, гостю
        видно по домену А3. Писем не будет — подтип `default=False`,
        подписчиков у него нет, `_notify_thread` выйдет на пустых
        получателях. Автор follower'ом не станет: `mail_create_nosubscribe`
        форсится нашим `message_post`, а партнёр-неюзер всё равно был бы
        отфильтрован.
        """
        self.ensure_one()
        participant = self.sudo()
        body = (body or '').strip()
        attachment_ids = list(attachment_ids or [])
        if not body and not attachment_ids:
            return self.env['mail.message'], _("The message cannot be empty.")
        if len(body) > MAX_GUEST_BODY:
            return self.env['mail.message'], _("The message is too long.")
        record = participant._streams_record()
        if not record:
            return self.env['mail.message'], _("This chat is no longer active.")
        # sudo обязателен: message_post проверяет права на чтение записи
        message = record.with_context(
            streams_guest_post=True).message_post(
                body=plaintext2html(body) if body else '',
                author_id=participant.partner_id.id,
                message_type='comment',
                subtype_xmlid='streams.mt_message',
                attachment_ids=attachment_ids[:MAX_GUEST_ATTACHMENTS])
        return message, False

    def _streams_own_message(self, message_id):
        """Своё сообщение гостя в пределах окна правки (§9.4)."""
        self.ensure_one()
        participant = self.sudo()
        message = self._streams_visible_message(message_id)
        if not message:
            return self.env['mail.message'], _("Message not found.")
        if message.author_id != participant.partner_id:
            return (self.env['mail.message'],
                    _("You can only change your own messages."))
        window = self._streams_edit_window()
        if not message.date or (
                fields.Datetime.now() - message.date).total_seconds() > window:
            return (self.env['mail.message'],
                    _("The time window for changing this message is over."))
        return message, False

    def _streams_update_message(self, message_id, body):
        """Правка своего сообщения ядровым `_message_update_content` (Р7).

        В 19 правка живёт на треде (`mail_thread.py:4932`), а не на самом
        сообщении; гейт `_check_can_update_message_content` снимается
        контекстом `streams_guest_edit` (см. наш `mail_thread`).
        `attachment_ids=None` означает «вложения не трогать»: передать их
        списком нельзя — `_process_attachments_for_post` под публичным
        uid оставил бы только pending-вложения и уже привязанные выпали бы.
        """
        self.ensure_one()
        message, error = self._streams_own_message(message_id)
        if error:
            return message, error
        body = (body or '').strip()
        if not body:
            return self.env['mail.message'], _("The message cannot be empty.")
        if len(body) > MAX_GUEST_BODY:
            return self.env['mail.message'], _("The message is too long.")
        record = self.sudo()._streams_record()
        if not record:
            return self.env['mail.message'], _("This chat is no longer active.")
        record.with_context(streams_guest_edit=True)._message_update_content(
            message.sudo(), body=plaintext2html(body), attachment_ids=None)
        self._streams_notify_message_update(message)
        return message, False

    def _streams_delete_message(self, message_id):
        """Удаление гостем = сообщение становится заметкой (решение 4).

        Тело не опустошается: сообщение переподтипливается в
        `mail.mt_note` с префиксом. Гость его больше не видит (note не
        входит в гостевой домен §9.4), сотрудники видят содержимое в
        потоке Notes — след и аудит сохраняются без новых сущностей.
        Вложения выпадают из гостевой выдачи вместе с сообщением.
        """
        self.ensure_one()
        message, error = self._streams_own_message(message_id)
        if error:
            return message, error
        note_subtype_id = self.env['ir.model.data']._xmlid_to_res_id(
            'mail.mt_note', raise_if_not_found=False)
        if not note_subtype_id:
            return self.env['mail.message'], _("Deletion is not available.")
        body = '<p><em>%s</em></p>%s' % (
            GUEST_DELETED_PREFIX, message.body or '')
        message.sudo().write({
            'subtype_id': note_subtype_id,
            'body': body,
        })
        self._streams_notify_message_update(message)
        return message, False

    def _streams_toggle_reaction(self, message_id, content, add=True):
        """Реакция гостя (Р8).

        Ядровый путь (`_message_reaction`) рассчитан на залогиненного
        пользователя или `mail.guest`, а наш гость — ни то, ни другое:
        под публичным uid партнёра взять неоткуда, поэтому пишем
        `mail.message.reaction` напрямую (поля в 19 те же: message_id,
        content, partner_id). Партнёр у гостя настоящий, так что его
        реакция неотличима от реакции сотрудника и корректно рисуется
        в Discuss.
        """
        self.ensure_one()
        if content not in GUEST_REACTIONS:
            return False, _("This reaction is not supported.")
        message = self._streams_visible_message(message_id)
        if not message:
            return False, _("Message not found.")
        partner = self.sudo().partner_id
        reaction_model = self.env['mail.message.reaction'].sudo()
        reaction = reaction_model.search([
            ('message_id', '=', message.id),
            ('content', '=', content),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if add and not reaction:
            reaction_model.create({
                'message_id': message.id,
                'content': content,
                'partner_id': partner.id,
            })
        elif not add and reaction:
            reaction.unlink()
        self._streams_notify_message_update(message)
        return True, False

    def _streams_attachment_message(self, attachment_id):
        """Сообщение, на котором висит вложение, если оно видно гостю (Р9)."""
        self.ensure_one()
        try:
            attachment_id = int(attachment_id)
        except (TypeError, ValueError):
            return self.env['mail.message']
        domain = self._streams_visible_domain() \
            & Domain('attachment_ids', 'in', [attachment_id])
        return self.env['mail.message'].sudo().search(domain, limit=1)

    def _streams_notify_message_update(self, message):
        """Сказать открытым клиентам сотрудников, что сообщение изменилось.

        Адресно и только тем, у кого есть право читать запись, — как и
        обычная проекция (`mail_thread._streams_broadcast`). Payload —
        персональный Store с самим сообщением: дефолтный
        `_to_store_defaults` уже отдаёт и body, и реакции, поэтому одна
        и та же рассылка покрывает правку, удаление и реакции.
        """
        self.ensure_one()
        record = self.sudo()._streams_record()
        if not record:
            return
        recipients = record._streams_readable_partners(
            self.sudo().channel_id.channel_partner_ids)
        if not recipients:
            return
        message_sudo = message.sudo()
        for recipient in recipients:
            Store(bus_channel=recipient).add(message_sudo).bus_send()

    def _streams_members(self):
        """Все участники канала (решение 3 от 2026-08-18).

        Гость видит и сотрудников (ФИО как есть, §9.4), и других внешних
        участников — с пометкой external, чтобы состав обсуждения был
        понятен. Отозванные доступы в список не входят: `active_test=True`
        ставится явно, потому что сам участник приходит сюда из
        `_streams_from_session`, а тот читает его с `active_test=False`.
        """
        self.ensure_one()
        channel = self.sudo().channel_id
        members = [
            {'name': member.display_name, 'is_external': False}
            for member in channel.channel_partner_ids
        ]
        externals = self.sudo().with_context(active_test=True).search([
            ('channel_id', '=', channel.id)])
        for external in externals:
            members.append({
                'name': external.partner_id.display_name,
                'is_external': True,
            })
        return members

    # ------------------------------------------------------------
    # АВТОПОДПИСКА ПРИГЛАСИВШЕГО (решение 6 от 2026-08-18)
    # ------------------------------------------------------------

    @api.model
    def _streams_subscribe_inviters(self, channel, author_partner):
        """Ответ клиента подписывает того, кто выдал ему доступ.

        Приглашение из чаттера подписчиком не делает (§5.1), поэтому без
        этого правила пригласивший ответа просто не увидел бы. Подписывается
        `invited_by_id` именно того участника, чей контакт написал: у разных
        гостей одного канала могут быть разные пригласившие.
        """
        if not channel or not author_partner:
            return False
        participants = self.sudo().with_context(active_test=True).search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', author_partner.id),
        ])
        if not participants:
            return False
        record = None
        subscribed = False
        for participant in participants:
            user = participant.invited_by_id
            if not user:
                continue
            if not user.active or user.share:
                _logger.warning(
                    'streams: пригласивший %s неактивен или внешний — подписка '
                    'на ответ гостя пропущена (участник %s)',
                    user.id, participant.id)
                continue
            if record is None:
                record = participant._streams_record()
            if not record:
                continue
            if user.partner_id in record.sudo().message_follower_ids.partner_id:
                continue
            record.sudo().message_subscribe(partner_ids=[user.partner_id.id])
            subscribed = True
            _logger.info(
                'streams: пригласивший %s подписан на %s,%s по ответу гостя',
                user.id, record._name, record.id)
        return subscribed

    # ------------------------------------------------------------
    # ДАЙДЖЕСТ (§9.6, А7)
    # ------------------------------------------------------------

    @api.model
    def _cron_streams_guest_digest(self):
        """Часовой дайджест отсутствующим гостям (§9.6).

        Присутствие проверяется на момент крона, а окно сообщений берётся
        за весь период — §9.6 требует, чтобы дайджест уходил целиком за
        час, даже если гость отключился в середине.
        """
        now = fields.Datetime.now()
        presence_timeout = self._streams_presence_timeout()
        absent_before = now - timedelta(seconds=presence_timeout)
        candidates = self.sudo().search([
            ('transport', '=', 'link'),
            ('channel_id.active', '=', True),
        ])
        interval = self._streams_digest_interval_hours()
        sent = self.env['mail.mail']
        for participant in candidates:
            try:
                if participant.last_seen \
                        and participant.last_seen > absent_before:
                    continue
                if not participant.partner_id.email:
                    _logger.debug(
                        'streams: у участника %s нет email — дайджест '
                        'пропущен', participant.id)
                    continue
                since = participant.last_digest_sent \
                    or (now - timedelta(hours=interval))
                if not participant._streams_digest_message_count(since):
                    continue
                if participant.is_link_consumed:
                    # ротируем только сожжённые ссылки (Р12): несожжённая
                    # лежит в неоткрытом письме-приглашении
                    link_url = participant._streams_issue_link()
                else:
                    link_url = participant.link_url
                mail = participant._streams_send_template(
                    'streams.mail_template_guest_digest', link_url)
                participant.write({'last_digest_sent': now})
                sent |= mail
            except Exception:
                # падение по одному участнику не должно ронять весь крон
                _logger.exception(
                    'streams: дайджест участнику %s не отправлен',
                    participant.id)
        if sent:
            _logger.info(
                'streams: гостевой дайджест — %s писем', len(sent))
        return sent

    @api.model
    def _streams_digest_interval_hours(self):
        """Интервал крона дайджеста; при любой неожиданности — час."""
        cron = self.env.ref(
            'streams.ir_cron_streams_guest_digest', raise_if_not_found=False)
        if cron and cron.sudo().interval_type == 'hours' \
                and cron.sudo().interval_number > 0:
            return cron.sudo().interval_number
        return 1

    def _streams_digest_message_count(self, since):
        """Сколько новых видимых гостю сообщений появилось после `since`.

        Собственные сообщения гостя не считаются: писать себе дайджест
        бессмысленно.
        """
        self.ensure_one()
        domain = (
            self.env['mail.message']._streams_guest_message_domain(self)
            & Domain('date', '>', since)
            & Domain('author_id', '!=', self.sudo().partner_id.id)
        )
        return self.env['mail.message'].sudo().search_count(domain)
