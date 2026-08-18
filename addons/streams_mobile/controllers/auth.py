# -*- encoding: utf-8 -*-
"""Аутентификация мобильного клиента (§2 design-phase6).

Все маршруты v1 — jsonrpc/POST. Ошибки отдаются словарём
``{'error': {'code': ..., 'message': ...}}``: мобильному клиенту нужны
машинные коды, а не JSON-RPC-трейсбеки.
"""
import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

_logger = logging.getLogger(__name__)


def mobile_error(code, message):
    return {'error': {'code': code, 'message': message}}


def mobile_auth():
    """Устройство по заголовку Authorization; env переключается на владельца.

    Возвращает (device, error): при ошибке device пуст, error — готовый
    ответ. Дальше запрос выполняется правами пользователя, БЕЗ sudo —
    инвариант ТЗ.
    """
    header = request.httprequest.headers.get('Authorization', '')
    token = header[7:] if header.startswith('Bearer ') else ''
    device = request.env['streams.mobile.device']._streams_from_token(token)
    if not device:
        return device, mobile_error('auth_failed', 'Invalid or revoked token')
    request.update_env(user=device.user_id.id)
    device._streams_touch()
    return device, None


class StreamsMobileAuthController(http.Controller):

    @http.route('/streams/mobile/v1/auth/login', type='jsonrpc',
                auth='none', methods=['POST'], csrf=False)
    def login(self, login=None, password=None, totp_code=None,
              device_name=None, platform='other', app_version=None):
        if not login or not password:
            return mobile_error('bad_request', 'login and password required')
        users = request.env['res.users'].sudo()
        try:
            auth_info = users._login(
                {'type': 'password', 'login': login, 'password': password},
                {'interactive': False})
        except AccessDenied:
            return mobile_error('auth_failed', 'Wrong login or password')
        user = users.browse(auth_info['uid'])
        if user.share:
            # мобильный клиент — только для внутренних (ТЗ: гость вне рамок)
            return mobile_error('auth_failed', 'Internal users only')
        if user._mfa_type():
            if not totp_code:
                return mobile_error('totp_required', 'TOTP code required')
            code = str(totp_code).strip().replace(' ', '')
            if not code.isdigit():
                return mobile_error('totp_invalid', 'Malformed TOTP code')
            try:
                user.with_user(user)._check_credentials(
                    {'type': 'totp', 'token': int(code)},
                    {'interactive': False})
            except AccessDenied:
                return mobile_error('totp_invalid', 'Wrong TOTP code')
        device, token = request.env[
            'streams.mobile.device']._streams_issue(
                user, name=device_name, platform=platform,
                app_version=app_version)
        return {
            'token': token,
            'device_id': device.id,
            'user': {
                'id': user.id,
                'name': user.name,
                'partner_id': user.partner_id.id,
            },
            'server_version': request.env['ir.module.module'].sudo(
            ).search([('name', '=', 'streams_mobile')],
                     limit=1).installed_version or '',
        }

    @http.route('/streams/mobile/v1/auth/logout', type='jsonrpc',
                auth='public', methods=['POST'], csrf=False)
    def logout(self):
        device, error = mobile_auth()
        if error:
            return error
        device.action_revoke()
        return {'ok': True}

    @http.route('/streams/mobile/v1/push/register', type='jsonrpc',
                auth='public', methods=['POST'], csrf=False)
    def push_register(self, push_token=None, push_enabled=True):
        device, error = mobile_auth()
        if error:
            return error
        device.sudo().write({
            'push_token': push_token or False,
            'push_enabled': bool(push_enabled),
        })
        return {'ok': True}
