# -*- encoding: utf-8 -*-
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# last_activity пишется не чаще раза в это число секунд: поле нужно для
# «протухших» устройств и диагностики, а не для точного presence.
ACTIVITY_THROTTLE_SECONDS = 300


class StreamsMobileDevice(models.Model):
    """Устройство мобильного клиента и его токен (§2 design-phase6).

    В БД хранится только sha256 секрета: утечка дампа не даёт рабочих
    токенов. Клиент получает строку ``<device_id>|<secret>`` один раз,
    при логине.
    """
    _name = 'streams.mobile.device'
    _description = 'Streams Mobile Device'
    _order = 'id desc'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, index=True,
        ondelete='cascade')
    name = fields.Char(string='Device Name')
    platform = fields.Selection(
        [('ios', 'iOS'), ('android', 'Android'), ('other', 'Other')],
        default='other', required=True)
    app_version = fields.Char(string='App Version')
    token_hash = fields.Char(
        string='Token Hash', index=True, groups='base.group_system')
    push_token = fields.Char(
        string='Push Token', groups='base.group_system',
        help="FCM registration token of the device.")
    push_enabled = fields.Boolean(string='Push Enabled', default=True)
    last_activity = fields.Datetime(string='Last Activity')
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------
    # ТОКЕНЫ
    # ------------------------------------------------------------

    @api.model
    def _streams_hash(self, secret):
        return hashlib.sha256(secret.encode()).hexdigest()

    @api.model
    def _streams_issue(self, user, name=None, platform='other',
                       app_version=None):
        """Выдать устройство и его секрет. Вызывается только login-контроллером
        после проверки пароля (создание устройств пользователю недоступно).
        """
        secret = secrets.token_urlsafe(32)
        device = self.sudo().create({
            'user_id': user.id,
            'name': name or 'Mobile device',
            'platform': platform if platform in ('ios', 'android') else 'other',
            'app_version': app_version,
            'token_hash': self._streams_hash(secret),
            'last_activity': fields.Datetime.now(),
        })
        _logger.info(
            'streams_mobile: выдан токен устройства %s пользователю %s',
            device.id, user.id)
        return device, '%s|%s' % (device.id, secret)

    @api.model
    def _streams_from_token(self, token):
        """Устройство по строке ``Authorization: Bearer <id>|<secret>``.

        Пустой recordset на любую ошибку; никаких исключений — код ответа
        решает контроллер. Сверка хеша — константное время.
        """
        if not token or '|' not in token:
            return self.browse()
        device_id, _sep, secret = token.partition('|')
        if not device_id.isdigit() or not secret:
            return self.browse()
        device = self.sudo().browse(int(device_id)).exists()
        if not device or not device.active or not device.token_hash:
            return self.browse()
        if not hmac.compare_digest(
                device.token_hash, self._streams_hash(secret)):
            _logger.warning(
                'streams_mobile: неверный токен для устройства %s', device.id)
            return self.browse()
        user = device.user_id
        if not user.active or user.share:
            return self.browse()
        return device

    def _streams_touch(self):
        self.ensure_one()
        now = fields.Datetime.now()
        last = self.last_activity
        if not last or now - last > timedelta(
                seconds=ACTIVITY_THROTTLE_SECONDS):
            self.sudo().write({'last_activity': now})

    # ------------------------------------------------------------
    # ОТЗЫВ
    # ------------------------------------------------------------

    def action_revoke(self):
        """Отзыв устройства: токен перестаёт работать немедленно."""
        self.sudo().write({'active': False, 'token_hash': False})
        _logger.info('streams_mobile: отозваны устройства %s', self.ids)

    @api.model
    def _streams_revoke_for_users(self, users):
        """Инвалидация всех токенов пользователей (смена пароля, § ТЗ)."""
        devices = self.sudo().with_context(active_test=True).search([
            ('user_id', 'in', users.ids)])
        if devices:
            devices.action_revoke()
