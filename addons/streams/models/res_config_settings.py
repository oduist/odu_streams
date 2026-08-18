# -*- encoding: utf-8 -*-
from odoo import models, fields, api

from .mail_notify import (
    DEFAULT_NOTIFY_TIMEOUT,
    DEFAULT_TRANSCRIPTION_MODEL,
    NOTIFY_TIMEOUT_PARAM,
    OPENAI_API_KEY_PARAM,
    TRANSCRIPTION_MODEL_PARAM,
)
from .mail_channel_external_participant import (
    DEFAULT_EDIT_WINDOW,
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PRESENCE_TIMEOUT,
    DEFAULT_SESSION_DAYS,
    GUEST_EDIT_WINDOW_PARAM,
    GUEST_MAX_UPLOAD_MB_PARAM,
    GUEST_POLL_INTERVAL_PARAM,
    GUEST_PRESENCE_TIMEOUT_PARAM,
    GUEST_SESSION_DAYS_PARAM,
)


class ResConfigSettings(models.TransientModel):
    """Настройки продукта (§14).

    Ключ OpenAI не дублируется новым параметром: он уже живёт в базе под
    именем `openai_api_key` (velesagro_crm), поэтому здесь другое имя поля
    и тот же `config_parameter`.
    """
    _inherit = 'res.config.settings'

    streams_notify_timeout = fields.Integer(
        string='Notification Popup Timeout',
        config_parameter=NOTIFY_TIMEOUT_PARAM,
        default=DEFAULT_NOTIFY_TIMEOUT,
        help="Seconds a non-sticky notification popup stays on screen.")
    streams_openai_api_key = fields.Char(
        # ярлык отличается от velesagro_crm намеренно: поле то же самое,
        # а два одинаковых ярлыка на res.config.settings ядро ругает
        string='Voice Transcription API Key',
        config_parameter=OPENAI_API_KEY_PARAM,
        help="Used to transcribe voice notifications. Leave empty to send "
             "voice messages without a transcript.")
    streams_transcription_model = fields.Char(
        string='Transcription Model',
        config_parameter=TRANSCRIPTION_MODEL_PARAM,
        default=DEFAULT_TRANSCRIPTION_MODEL,
        help="OpenAI model used to transcribe voice notifications.")

    # ------------------------------------------------------------
    # ГОСТЕВОЙ ДОСТУП (§9, §14)
    # ------------------------------------------------------------

    streams_guest_session_days = fields.Integer(
        string='Guest Session Lifetime',
        config_parameter=GUEST_SESSION_DAYS_PARAM,
        default=DEFAULT_SESSION_DAYS,
        help="Days a guest chat session stays valid. The session is extended "
             "on every visit.")
    streams_guest_poll_interval = fields.Integer(
        string='Guest Poll Interval',
        config_parameter=GUEST_POLL_INTERVAL_PARAM,
        default=DEFAULT_POLL_INTERVAL,
        help="Seconds between two refreshes of the guest chat page.")
    streams_guest_edit_window = fields.Integer(
        string='Guest Edit Window',
        config_parameter=GUEST_EDIT_WINDOW_PARAM,
        default=DEFAULT_EDIT_WINDOW,
        help="Seconds during which a guest may edit or delete their own "
             "message.")
    streams_guest_presence_timeout = fields.Integer(
        string='Guest Presence Timeout',
        config_parameter=GUEST_PRESENCE_TIMEOUT_PARAM,
        default=DEFAULT_PRESENCE_TIMEOUT,
        help="A guest without any activity for that many seconds counts as "
             "absent and receives the hourly digest.")
    streams_guest_max_upload_mb = fields.Integer(
        string='Guest Upload Limit (MB)',
        config_parameter=GUEST_MAX_UPLOAD_MB_PARAM,
        default=DEFAULT_MAX_UPLOAD_MB,
        help="Maximum size of a single file a guest may attach.")
    streams_guest_digest_hours = fields.Integer(
        string='Guest Digest Interval (hours)',
        default=1,
        help="How often absent guests are notified about new messages.")

    @api.model
    def get_values(self):
        """Интервал дайджеста живёт в самом кроне, а не в параметрах."""
        values = super().get_values()
        cron = self.env.ref(
            'streams.ir_cron_streams_guest_digest', raise_if_not_found=False)
        if cron:
            values['streams_guest_digest_hours'] = \
                cron.sudo().interval_number or 1
        return values

    def set_values(self):
        result = super().set_values()
        cron = self.env.ref(
            'streams.ir_cron_streams_guest_digest', raise_if_not_found=False)
        if cron and self.streams_guest_digest_hours > 0:
            cron.sudo().write({
                'interval_number': self.streams_guest_digest_hours,
                'interval_type': 'hours',
            })
        return result
