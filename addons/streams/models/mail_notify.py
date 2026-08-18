# -*- encoding: utf-8 -*-
import logging
from datetime import timedelta

import requests

from odoo import models, fields, api, tools, _
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Параметры продукта (§14). Ключ OpenAI переиспользуется из velesagro_crm:
# заводить второй параметр под тот же секрет незачем.
NOTIFY_TIMEOUT_PARAM = 'streams.notify_timeout'
TRANSCRIPTION_MODEL_PARAM = 'streams.transcription_model'
OPENAI_API_KEY_PARAM = 'openai_api_key'

DEFAULT_NOTIFY_TIMEOUT = 10
DEFAULT_TRANSCRIPTION_MODEL = 'whisper-1'
MIN_NOTIFY_TIMEOUT = 3
MAX_NOTIFY_TIMEOUT = 300

OPENAI_TRANSCRIPTION_URL = 'https://api.openai.com/v1/audio/transcriptions'

# Голос (§12.3): белый список mimetype, лимит OpenAI (25 МБ) и продукта (5 мин).
#
# `video/*` в списке не опечатка: MediaRecorder отдаёт `audio/webm`, но
# mimetype вложения считает сервер по имени файла (`ir.attachment
# ._compute_mimetype` → `mimetypes.guess_type`), а stdlib знает `.webm`
# только как `video/webm`. Проверено живьём в среде: .webm → video/webm,
# .ogg → audio/ogg, .m4a → audio/mpeg.
VOICE_MIMETYPES = (
    'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/mpeg',
    'audio/wav', 'audio/x-wav', 'audio/x-m4a', 'audio/mp3',
    'video/webm', 'video/ogg', 'video/mp4',
)
VOICE_EXTENSIONS = (
    '.webm', '.ogg', '.oga', '.m4a', '.mp4', '.mp3', '.wav',
)
MAX_VOICE_SIZE = 25 * 1024 * 1024
MAX_VOICE_DURATION = 5 * 60

# Накопившиеся попапы офлайн-получателя (§12.4)
PENDING_POPUP_LIMIT = 20
PENDING_POPUP_DAYS = 7

# Задание транскрипции, зависшее дольше этого, переставляется кроном (А8)
TRANSCRIPT_STUCK_MINUTES = 10

# Типы шины. Доставка в 19 — `partner._bus_send(type, payload)`; префикс
# `streams.` отделяет наши типы от ядровых (`mail.record/insert` и т.п.).
BUS_NEW = 'streams.notify/new'
BUS_UPDATE = 'streams.notify/update'
BUS_COUNTER = 'streams.notify/counter'


class MailNotify(models.Model):
    """Приоритетное адресное уведомление (§4.5, §12).

    Уведомление сознательно **не** `mail.message`: у него нет чаттера, оно
    не создаёт каналов записей и не проходит через классификатор потоков.
    Доставка — попапом у получателя и лентой личного канала Notifications.
    """
    _name = 'mail.notify'
    _description = 'Priority Notification'
    _order = 'id desc'

    author_id = fields.Many2one(
        'res.users', string='Author', required=True, index=True,
        ondelete='restrict', default=lambda self: self.env.user)
    body = fields.Html(string='Body')
    attachment_ids = fields.Many2many(
        'ir.attachment', 'mail_notify_attachment_rel',
        'notify_id', 'attachment_id', string='Attachments')
    voice_attachment_id = fields.Many2one(
        'ir.attachment', string='Voice Message', ondelete='set null')
    voice_duration = fields.Integer(
        string='Voice Duration', help="Length of the voice message, seconds.")
    transcript = fields.Text(string='Transcript')
    transcript_state = fields.Selection(
        [
            ('none', 'Not Requested'),
            ('queued', 'Queued'),
            ('done', 'Done'),
            ('failed', 'Failed'),
        ],
        string='Transcription State', default='none', required=True)
    res_model = fields.Char(string='Related Document Model')
    res_id = fields.Integer(string='Related Document ID')
    record_name = fields.Char(
        string='Related Document Name',
        help="Name of the related record as of the moment the notification "
             "was sent.")
    is_sticky = fields.Boolean(
        string='Sticky',
        help="The popup stays until the recipient closes it.")
    timeout = fields.Integer(
        string='Popup Timeout',
        default=lambda self: self._streams_default_timeout(),
        help="Seconds the popup stays on screen when it is not sticky.")
    parent_id = fields.Many2one(
        'mail.notify', string='Parent Notification', ondelete='set null',
        index=True)
    recipient_ids = fields.One2many(
        'mail.notify.recipient', 'notify_id', string='Recipients')

    _streams_record_idx = models.Index("(res_model, res_id)")

    # ------------------------------------------------------------
    # НАСТРОЙКИ (§14)
    # ------------------------------------------------------------

    @api.model
    def _streams_default_timeout(self):
        """Таймаут попапа из системных параметров, зажатый в допустимое."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            NOTIFY_TIMEOUT_PARAM, DEFAULT_NOTIFY_TIMEOUT)
        try:
            value = int(param)
        except (TypeError, ValueError):
            value = DEFAULT_NOTIFY_TIMEOUT
        return min(max(value, MIN_NOTIFY_TIMEOUT), MAX_NOTIFY_TIMEOUT)

    @api.model
    def _streams_openai_key(self):
        return (self.env['ir.config_parameter'].sudo().get_param(
            OPENAI_API_KEY_PARAM) or '').strip()

    @api.model
    def _streams_transcription_model(self):
        return (self.env['ir.config_parameter'].sudo().get_param(
            TRANSCRIPTION_MODEL_PARAM) or DEFAULT_TRANSCRIPTION_MODEL).strip()

    # ------------------------------------------------------------
    # ПРАВИЛА МОДЕЛИ (§12.2, §12.3)
    # ------------------------------------------------------------

    @api.model
    def _streams_normalize_vals(self, vals):
        """Голос форсирует sticky, таймаут зажимается в допустимый диапазон."""
        if vals.get('voice_attachment_id'):
            vals['is_sticky'] = True
        if 'timeout' in vals:
            try:
                timeout = int(vals['timeout'] or 0)
            except (TypeError, ValueError):
                timeout = self._streams_default_timeout()
            vals['timeout'] = min(
                max(timeout, MIN_NOTIFY_TIMEOUT), MAX_NOTIFY_TIMEOUT)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._streams_normalize_vals(dict(vals))
                     for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        vals = self._streams_normalize_vals(dict(vals))
        result = super().write(vals)
        if 'is_sticky' in vals and not vals.get('is_sticky'):
            # sticky снимают, а голос остался — попап закроется раньше, чем
            # дослушают запись (§12.3). Возвращаем принудительно.
            voiced = self.filtered(lambda notify: notify.voice_attachment_id)
            if voiced:
                super(MailNotify, voiced).write({'is_sticky': True})
        return result

    # ------------------------------------------------------------
    # ВАЛИДАЦИЯ ОТПРАВКИ
    # ------------------------------------------------------------

    @api.model
    def _streams_check_recipients(self, user_ids):
        """Получатели — только активные внутренние пользователи (§12.2)."""
        user_ids = [int(user_id) for user_id in (user_ids or []) if user_id]
        if not user_ids:
            raise UserError(_("Select at least one recipient."))
        users = self.env['res.users'].sudo().with_context(
            active_test=False).browse(list(set(user_ids))).exists()
        if not users:
            raise UserError(_("Select at least one recipient."))
        invalid = users.filtered(lambda user: user.share or not user.active)
        if invalid:
            raise ValidationError(_(
                "Notifications can only be sent to active internal users."))
        return users

    @api.model
    def _streams_check_voice(self, attachment, duration):
        """Формат и объём голоса проверяет сервер, а не только виджет."""
        if not attachment:
            return
        name = (attachment.name or '').lower()
        if attachment.mimetype not in VOICE_MIMETYPES \
                and not name.endswith(VOICE_EXTENSIONS):
            raise UserError(_(
                "This audio format is not supported for voice notifications."))
        if attachment.file_size and attachment.file_size > MAX_VOICE_SIZE:
            raise UserError(_("The voice message is too large (25 MB max)."))
        if duration and duration > MAX_VOICE_DURATION:
            raise UserError(_("The voice message is too long (5 minutes max)."))

    # ------------------------------------------------------------
    # ВЛОЖЕНИЯ (А7)
    # ------------------------------------------------------------

    def _streams_bind_attachments(self, attachment_ids):
        """Перепривязать pending-вложения композера на уведомление.

        Копия ядрового приёма (в 19 — `mail.thread
        ._process_attachments_for_post`): `/mail/attachment/upload` с
        `is_pending` по-прежнему заливает вложение до создания записи как
        `mail.compose.message` с `res_id=0`, и оно доступно только своему
        создателю. Ядровый фильтр принимает ещё `mail.scheduled.message`,
        но к нашему композеру этот путь отношения не имеет.
        """
        self.ensure_one()
        if not attachment_ids:
            return self.env['ir.attachment']
        attachments = self.env['ir.attachment'].sudo().browse(
            [int(attachment_id) for attachment_id in attachment_ids]).exists()
        pending = attachments.filtered(
            lambda attachment: attachment.res_model == 'mail.compose.message'
            and not attachment.res_id
            and attachment.create_uid.id == self.env.uid)
        if pending:
            pending.write({'res_model': self._name, 'res_id': self.id})
        return attachments

    # ------------------------------------------------------------
    # ПУБЛИЧНЫЙ API (А5)
    # ------------------------------------------------------------

    @api.model
    def streams_notify_send(self, vals):
        """Отправить уведомление (§12.2)."""
        notify = self._streams_create(vals)
        return {'id': notify.id}

    @api.model
    def streams_notify_reply(self, parent_id, vals):
        """Ответ на уведомление (§12.6): получатель — только автор родителя."""
        parent = self.browse(int(parent_id)).exists()
        if not parent:
            raise UserError(_("The notification you reply to no longer exists."))
        # право на чтение родителя = я его автор или получатель (ir.rule)
        parent.check_access('read')
        vals = dict(vals or {})
        vals['user_ids'] = [parent.author_id.id]
        vals.setdefault('is_sticky', parent.is_sticky)
        vals.setdefault('timeout', parent.timeout)
        notify = self._streams_create(vals, parent=parent)
        return {'id': notify.id}

    def _streams_create(self, vals, parent=None):
        """Общая часть отправки и ответа."""
        vals = dict(vals or {})
        users = self._streams_check_recipients(vals.get('user_ids'))
        body = vals.get('body') or ''
        values = {
            'body': tools.plaintext2html(body) if body else '',
            'is_sticky': bool(vals.get('is_sticky')),
            'parent_id': parent.id if parent else False,
        }
        if vals.get('timeout'):
            values['timeout'] = vals['timeout']
        res_model = vals.get('res_model') or False
        res_id = int(vals.get('res_id') or 0)
        if res_model and res_id:
            values.update({
                'res_model': res_model,
                'res_id': res_id,
                'record_name': self._streams_record_name(res_model, res_id),
            })
        voice_id = vals.get('voice_attachment_id')
        voice = self.env['ir.attachment']
        if voice_id:
            voice = self.env['ir.attachment'].sudo().browse(
                int(voice_id)).exists()
            self._streams_check_voice(voice, int(vals.get('voice_duration') or 0))
            values.update({
                'voice_attachment_id': voice.id,
                'voice_duration': int(vals.get('voice_duration') or 0),
            })
        notify = self.create(values)
        attachment_ids = list(vals.get('attachment_ids') or [])
        if voice:
            attachment_ids.append(voice.id)
        notify._streams_bind_attachments(attachment_ids)
        # в m2m попадают только вложения, реально привязанные к уведомлению:
        # чужой id из RPC не должен засветить даже имя файла в ленте
        bound = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', '=', notify.id),
        ])
        plain_attachments = [
            attachment.id for attachment in bound if attachment.id != voice.id
        ]
        if plain_attachments:
            notify.write({'attachment_ids': [(6, 0, plain_attachments)]})
        notify.recipient_ids = [
            (0, 0, {'user_id': user.id}) for user in users]
        notify._streams_enqueue_transcription()
        notify._streams_prepare_channels(users)
        notify._streams_broadcast_new()
        _logger.info(
            'streams: уведомление %s отправлено пользователям %s',
            notify.id, users.ids)
        return notify

    @api.model
    def _streams_record_name(self, res_model, res_id):
        """Снимок имени записи: лента не ходит по чужим моделям ради имени."""
        if res_model not in self.env:
            return False
        record = self.env[res_model].sudo().with_context(
            active_test=False).browse(res_id).exists()
        return record.display_name if record else False

    def _streams_prepare_channels(self, users):
        """Личные каналы Notifications автора и получателей (§12.5)."""
        self.ensure_one()
        channel_model = self.env['discuss.channel']
        for user in (self.author_id | users):
            channel_model._streams_get_notifications_channel(user)

    # ------------------------------------------------------------
    # ЛЕНТА (§12.5)
    # ------------------------------------------------------------

    @api.model
    def streams_notify_feed(self, box='received', limit=30, before_id=None):
        """Лента личного канала Notifications: Received либо Sent."""
        limit = min(max(int(limit or 30), 1), 100)
        if box == 'sent':
            domain = [('author_id', '=', self.env.uid)]
        else:
            domain = [('recipient_ids.user_id', '=', self.env.uid)]
        if before_id:
            domain = domain + [('id', '<', int(before_id))]
        notifies = self.search(domain, limit=limit)
        if box == 'sent':
            return [
                notify._streams_payload(with_recipients=True)
                for notify in notifies
            ]
        rows = self.env['mail.notify.recipient'].search([
            ('notify_id', 'in', notifies.ids),
            ('user_id', '=', self.env.uid),
        ])
        row_by_notify = {row.notify_id.id: row for row in rows}
        return [
            notify._streams_payload(recipient=row_by_notify.get(notify.id))
            for notify in notifies
        ]

    def _streams_payload(self, recipient=None, with_recipients=False):
        """Общая форма элемента ленты; она же payload шины (А5)."""
        self.ensure_one()
        voice = False
        if self.voice_attachment_id:
            voice = {
                'id': self.voice_attachment_id.id,
                'mimetype': self.voice_attachment_id.mimetype or '',
                'duration': self.voice_duration,
            }
        payload = {
            'id': self.id,
            'date': fields.Datetime.to_string(self.create_date),
            'author': {
                'id': self.author_id.id,
                'name': self.author_id.display_name or '',
            },
            'body': self.body or '',
            'is_sticky': self.is_sticky,
            'timeout': self.timeout,
            'res_model': self.res_model or False,
            'res_id': self.res_id or False,
            'record_name': self.record_name or '',
            'attachments': [
                {
                    'id': attachment.id,
                    'name': attachment.name,
                    'mimetype': attachment.mimetype or '',
                    'size': attachment.file_size,
                }
                for attachment in self.attachment_ids
                if attachment != self.voice_attachment_id
            ],
            'voice': voice,
            'transcript': self.transcript or False,
            'transcript_state': self.transcript_state,
            'parent_id': self.parent_id.id or False,
        }
        if recipient is not None and recipient:
            payload['read_date'] = fields.Datetime.to_string(
                recipient.read_date) if recipient.read_date else False
            payload['popup_shown'] = recipient.popup_shown
        if with_recipients:
            payload['recipients'] = [
                {
                    'user_id': row.user_id.id,
                    'name': row.user_id.display_name or '',
                    'read_date': fields.Datetime.to_string(row.read_date)
                                 if row.read_date else False,
                }
                for row in self.recipient_ids
            ]
        return payload

    # ------------------------------------------------------------
    # ПРОЧИТАННОСТЬ И СЧЁТЧИК (§12.5, §11.4)
    # ------------------------------------------------------------

    @api.model
    def _streams_notify_counter(self, user=None):
        """Непрочитанные уведомления пользователя."""
        user = user or self.env.user
        return self.env['mail.notify.recipient'].sudo().search_count([
            ('user_id', '=', user.id),
            ('read_date', '=', False),
        ])

    @api.model
    def streams_notify_mark_read(self, notify_ids):
        """Отметить прочитанным по доскроллу (§12.5)."""
        counter = self._streams_notify_counter()
        notify_ids = [int(notify_id) for notify_id in (notify_ids or [])]
        if not notify_ids:
            return {'counter': counter}
        rows = self.env['mail.notify.recipient'].search([
            ('notify_id', 'in', notify_ids),
            ('user_id', '=', self.env.uid),
            ('read_date', '=', False),
        ])
        if not rows:
            return {'counter': counter}
        # повторный mark_read не перетирает уже проставленное время
        rows.write({'read_date': fields.Datetime.now()})
        counter = self._streams_notify_counter()
        for row in rows:
            notify = row.sudo().notify_id
            notify.author_id.partner_id._bus_send(BUS_UPDATE, {
                'id': notify.id,
                'recipient': {
                    'user_id': row.user_id.id,
                    'name': row.user_id.display_name or '',
                    'read_date': fields.Datetime.to_string(row.read_date),
                },
            })
        self.env.user.partner_id._bus_send(BUS_COUNTER, {'counter': counter})
        return {'counter': counter}

    @api.model
    def streams_notify_popup_shown(self, notify_ids):
        """Попап показан — второй раз при следующем логине не всплывёт."""
        notify_ids = [int(notify_id) for notify_id in (notify_ids or [])]
        if not notify_ids:
            return True
        rows = self.env['mail.notify.recipient'].search([
            ('notify_id', 'in', notify_ids),
            ('user_id', '=', self.env.uid),
            ('popup_shown', '=', False),
        ])
        if rows:
            rows.write({'popup_shown': True})
        return True

    @api.model
    def streams_notify_open_channel(self):
        """Личный канал Notifications, создавая его при первом заходе.

        В 15 возвращался `channel_info()[0]`; в 19 формат клиента — Store,
        поэтому контракт: id канала плюс Store-payload его данных.
        """
        channel = self.env[
            'discuss.channel']._streams_get_notifications_channel()
        if not channel:
            return False
        return {
            'channel_id': channel.id,
            'data': Store().add(channel).get_result(),
        }

    # ------------------------------------------------------------
    # СТАРТ КЛИЕНТА (А9)
    # ------------------------------------------------------------

    @api.model
    def _streams_init_messaging(self):
        """Счётчик, канал и накопившиеся попапы одним куском payload'а."""
        channel = self.env[
            'discuss.channel']._streams_get_notifications_channel(create=False)
        limit_date = fields.Datetime.now() - timedelta(days=PENDING_POPUP_DAYS)
        rows = self.env['mail.notify.recipient'].search([
            ('user_id', '=', self.env.uid),
            ('popup_shown', '=', False),
            ('create_date', '>=', fields.Datetime.to_string(limit_date)),
        ], order='id desc', limit=PENDING_POPUP_LIMIT)
        pending = [
            row.notify_id._streams_payload(recipient=row)
            for row in reversed(rows)
        ]
        return {
            'counter': self._streams_notify_counter(),
            'channel_id': channel.id if channel else False,
            'default_timeout': self._streams_default_timeout(),
            'pending': pending,
        }

    # ------------------------------------------------------------
    # ШИНА (А6)
    # ------------------------------------------------------------

    def _streams_broadcast_new(self):
        """Разослать новое уведомление получателям (§12.4).

        Адресно, каждому на его партнёрский bus-канал; батчинг отправок
        в 19 делает precommit самой шины.
        """
        self.ensure_one()
        for row in self.sudo().recipient_ids:
            payload = self._streams_payload(recipient=row)
            payload['counter'] = self._streams_notify_counter(row.user_id)
            row.user_id.partner_id._bus_send(BUS_NEW, payload)

    def _streams_broadcast_update(self, patch):
        """Точечное обновление уведомления у автора и получателей."""
        self.ensure_one()
        notify = self.sudo()
        users = notify.author_id | notify.recipient_ids.mapped('user_id')
        for user in users:
            user.partner_id._bus_send(BUS_UPDATE, dict(patch, id=notify.id))

    # ------------------------------------------------------------
    # ТРАНСКРИПЦИЯ (§12.3, А8)
    # ------------------------------------------------------------

    def _streams_enqueue_transcription(self):
        """Голос уходит сразу, текст доезжает отдельным заданием (§12.3)."""
        self.ensure_one()
        if not self.voice_attachment_id:
            return False
        if not self._streams_openai_key():
            # ключа нет — просто аудио без текста (§12.3)
            return False
        self.sudo().write({'transcript_state': 'queued'})
        self.sudo().with_delay(
            priority=20,
            identity_key='streams.notify.transcript.%s' % self.id,
            description='Transcribe voice notification %s' % self.id,
        )._job_transcribe()
        return True

    def _job_transcribe(self):
        """Задание очереди: расшифровать голосовое сообщение."""
        # локальный импорт: без queue_job модуль всё равно не грузится, но
        # держать исключение рядом с местом использования нагляднее
        from odoo.addons.queue_job.exception import RetryableJobError

        self.ensure_one()
        notify = self.sudo()
        attachment = notify.voice_attachment_id
        if not attachment:
            return False
        api_key = self._streams_openai_key()
        if not api_key:
            notify.write({'transcript_state': 'none'})
            return False
        try:
            response = requests.post(
                OPENAI_TRANSCRIPTION_URL,
                headers={'Authorization': 'Bearer %s' % api_key},
                files={
                    'file': (
                        attachment.name or 'voice',
                        attachment.raw,
                        attachment.mimetype or 'audio/webm',
                    ),
                },
                data={
                    'model': self._streams_transcription_model(),
                    'response_format': 'json',
                },
                timeout=(10, 120),
            )
        except requests.RequestException as error:
            raise RetryableJobError(
                'OpenAI transcription request failed: %s' % error) from error
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableJobError(
                'OpenAI transcription returned HTTP %s.' % response.status_code)
        if response.status_code >= 400:
            _logger.warning(
                'streams: транскрипция уведомления %s отклонена, HTTP %s: %s',
                notify.id, response.status_code, response.text[:500])
            notify.write({'transcript_state': 'failed'})
            notify._streams_broadcast_update({'transcript_state': 'failed'})
            return False
        try:
            text = (response.json() or {}).get('text') or ''
        except ValueError as error:
            _logger.warning(
                'streams: транскрипция уведомления %s вернула не JSON: %s',
                notify.id, error)
            notify.write({'transcript_state': 'failed'})
            notify._streams_broadcast_update({'transcript_state': 'failed'})
            return False
        notify.write({'transcript': text, 'transcript_state': 'done'})
        notify._streams_broadcast_update({
            'transcript': text, 'transcript_state': 'done'})
        return True

    @api.model
    def _streams_cron_transcribe(self):
        """Страховка от выключенного jobrunner (А8).

        Задание могло не уехать вовсе (в Oduflow-средах `queue_job` не
        всегда server-wide) или упасть между ретраями — подбираем всё, что
        висит в `queued` дольше десяти минут.
        """
        limit_date = fields.Datetime.now() - timedelta(
            minutes=TRANSCRIPT_STUCK_MINUTES)
        stuck = self.sudo().search([
            ('transcript_state', '=', 'queued'),
            ('write_date', '<', fields.Datetime.to_string(limit_date)),
            ('voice_attachment_id', '!=', False),
        ], limit=50)
        if not stuck:
            return 0
        if not self._streams_openai_key():
            stuck.write({'transcript_state': 'none'})
            return 0
        for notify in stuck:
            notify.with_delay(
                priority=20,
                identity_key='streams.notify.transcript.%s' % notify.id,
                description='Transcribe voice notification %s' % notify.id,
            )._job_transcribe()
        _logger.info(
            'streams: переставлено заданий транскрипции: %s', len(stuck))
        # осиротевшие pending-вложения только считаем: ядро их тоже не чистит
        orphans = self.env['ir.attachment'].sudo().search_count([
            ('res_model', '=', 'mail.compose.message'),
            ('res_id', '=', 0),
            ('create_date', '<', fields.Datetime.to_string(
                fields.Datetime.now() - timedelta(days=1))),
        ])
        if orphans:
            _logger.info(
                'streams: осиротевших pending-вложений в базе: %s', orphans)
        return len(stuck)


class MailNotifyRecipient(models.Model):
    """Получатель уведомления и состояние доставки (§4.5)."""
    _name = 'mail.notify.recipient'
    _description = 'Priority Notification Recipient'
    _order = 'id desc'

    notify_id = fields.Many2one(
        'mail.notify', string='Notification', required=True,
        ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='Recipient', required=True, ondelete='cascade',
        index=True)
    partner_id = fields.Many2one(
        'res.partner', string='Recipient Contact',
        related='user_id.partner_id', store=True, index=True)
    read_date = fields.Datetime(string='Read On')
    popup_shown = fields.Boolean(string='Popup Shown', default=False)

    _notify_user_uniq = models.Constraint(
        'UNIQUE(notify_id, user_id)',
        "A notification reaches every recipient only once.")

    @api.constrains('user_id')
    def _check_internal_recipient(self):
        """Портальным и архивным уведомления не адресуются (§12.2)."""
        for recipient in self:
            user = recipient.user_id.sudo().with_context(active_test=False)
            if user.share or not user.active:
                raise ValidationError(_(
                    "Notifications can only be sent to active internal users."))

    def write(self, vals):
        """Получатель отмечает только своё состояние доставки.

        Тело и настройки попапа принадлежат автору: получатель не должен
        переписывать уведомление, которое ему прислали.
        """
        if not self.env.su:
            forbidden = set(vals) - {'read_date', 'popup_shown'}
            if forbidden:
                foreign = self.filtered(
                    lambda row: row.sudo().notify_id.author_id != self.env.user)
                if foreign:
                    raise AccessError(_(
                        "Only the author of a notification can change its "
                        "recipients."))
        return super().write(vals)
