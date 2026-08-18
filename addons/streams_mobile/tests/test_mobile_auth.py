# -*- encoding: utf-8 -*-
"""Аутентификация мобильного клиента (§2 design-phase6).

Два уровня:

* `TestMobileAuth` — модельный слой токенов: выдача, сверка, отзыв,
  инвалидация при смене пароля/архивации, ir.rule «только свои устройства»;
* `TestMobileAuthHttp` — HTTP-контракт login/logout/push register
  (JSON-RPC 2.0 конверт, как шлёт Flutter-клиент).
"""
import hashlib

from odoo.exceptions import AccessError
from odoo.tests import common, tagged
from odoo.tools import mute_logger

DEVICE_LOGGER = 'odoo.addons.streams_mobile.models.streams_mobile_device'
ACL_LOGGERS = (
    'odoo.addons.base.models.ir_model',
    'odoo.addons.base.models.ir_rule',
)


@tagged('post_install', '-at_install')
class TestMobileAuth(common.TransactionCase):
    """Токены устройств: модель `streams.mobile.device`."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        cls.user_a = cls.env['res.users'].create({
            'name': 'Streams Mobile Auth A',
            'login': 'streams.mobile.auth.a@example.com',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.user_b = cls.env['res.users'].create({
            'name': 'Streams Mobile Auth B',
            'login': 'streams.mobile.auth.b@example.com',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.portal_user = cls.env['res.users'].create({
            'name': 'Streams Mobile Auth Portal',
            'login': 'streams.mobile.auth.portal@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })

    # ------------------------------------------------------------
    # Хелперы
    # ------------------------------------------------------------

    @property
    def device_model(self):
        return self.env['streams.mobile.device']

    def _issue(self, user, **kwargs):
        return self.device_model._streams_issue(user, **kwargs)

    def _from_token(self, token):
        return self.device_model._streams_from_token(token)

    # 1
    def test_01_issue_token_format_and_hash(self):
        device, token = self._issue(
            self.user_a, name='Pixel 9 Pro', platform='android',
            app_version='1.0.0')
        self.assertTrue(device.exists())
        self.assertEqual(device.user_id, self.user_a)
        self.assertEqual(device.name, 'Pixel 9 Pro')
        self.assertEqual(device.platform, 'android')
        self.assertTrue(device.active)

        device_id, sep, secret = token.partition('|')
        self.assertEqual(sep, '|', 'токен — строка "<id>|<secret>"')
        self.assertEqual(int(device_id), device.id)
        self.assertTrue(secret, 'секретная часть не пуста')
        self.assertEqual(
            device.token_hash,
            hashlib.sha256(secret.encode()).hexdigest(),
            'в БД лежит только sha256 секрета')
        self.assertNotEqual(
            device.token_hash, secret,
            'секрет в открытом виде в БД не хранится')

    # 2
    def test_02_from_token(self):
        device_a, token_a = self._issue(self.user_a)
        device_b, token_b = self._issue(self.user_b)
        self.assertEqual(self._from_token(token_a), device_a)
        self.assertEqual(self._from_token(token_b), device_b)

        secret_a = token_a.partition('|')[2]
        secret_b = token_b.partition('|')[2]
        for garbage in (False, '', 'garbage', '123', '|', 'abc|def',
                        '%s|' % device_a.id):
            self.assertFalse(
                self._from_token(garbage),
                'мусорный токен %r отвергается' % (garbage,))
        with mute_logger(DEVICE_LOGGER):
            self.assertFalse(
                self._from_token('%s|%s' % (device_a.id, secret_b)),
                'чужой секрет с валидным id не проходит')
        self.assertFalse(
            self._from_token('%s|%s' % (device_b.id + 10 ** 6, secret_a)),
            'несуществующий id устройства не проходит')

    # 3
    def test_03_action_revoke(self):
        device, token = self._issue(self.user_a)
        self.assertEqual(self._from_token(token), device)
        device.action_revoke()
        self.assertFalse(
            self._from_token(token), 'отозванный токен гаснет немедленно')
        self.assertFalse(device.active)
        self.assertFalse(
            device.token_hash, 'hash очищен — токен не восстановить')

    # 4
    def test_04_password_change_revokes_devices(self):
        device_one, token_one = self._issue(self.user_a, name='One')
        device_two, token_two = self._issue(self.user_a, name='Two')
        device_b, token_b = self._issue(self.user_b)

        self.user_a.write({'password': 'NewSecret!2026'})
        self.assertFalse(
            self._from_token(token_one),
            'смена пароля гасит все токены пользователя')
        self.assertFalse(self._from_token(token_two))
        self.assertFalse(device_one.active)
        self.assertFalse(device_two.active)
        self.assertEqual(
            self._from_token(token_b), device_b,
            'устройства других пользователей не тронуты')

        self.user_b.write({'name': 'Streams Mobile Auth B Renamed'})
        self.assertEqual(
            self._from_token(token_b), device_b,
            'смена прочих полей токены не отзывает')
        self.assertTrue(device_b.active)

    # 5
    def test_05_archived_user_cannot_authenticate(self):
        device, token = self._issue(self.user_a)
        self.assertEqual(self._from_token(token), device)
        self.user_a.write({'active': False})
        self.assertFalse(
            self._from_token(token),
            'архивный пользователь Bearer-аутентификацию не проходит')
        self.assertTrue(
            device.active,
            'устройство не отозвано — гасит именно проверка пользователя')

    # 6
    def test_06_share_user_rejected_by_from_token(self):
        device, token = self._issue(self.portal_user)
        self.assertTrue(
            device.exists(),
            'модельный слой устройство выдать может — отсекает контроллер')
        self.assertEqual(device.user_id, self.portal_user)
        self.assertFalse(
            self._from_token(token),
            'share-пользователь Bearer-аутентификацию не проходит')

    # 7
    def test_07_ir_rule_own_devices_only(self):
        device_a, _token_a = self._issue(self.user_a)
        device_b, _token_b = self._issue(self.user_b)

        model_a = self.device_model.with_user(self.user_a)
        visible = model_a.search([])
        self.assertIn(device_a, visible)
        self.assertNotIn(
            device_b, visible, 'чужие устройства из поиска исключены')
        self.assertEqual(visible.mapped('user_id'), self.user_a)

        with mute_logger(*ACL_LOGGERS), self.assertRaises(AccessError):
            device_b.with_user(self.user_a).read(['name'])
        with mute_logger(*ACL_LOGGERS), self.assertRaises(AccessError):
            device_b.with_user(self.user_a).write({'name': 'hacked'})

        device_a.with_user(self.user_a).write({'name': 'My phone'})
        self.assertEqual(
            device_a.name, 'My phone',
            'своё устройство пользователь править может')

        with mute_logger(*ACL_LOGGERS), self.assertRaises(AccessError):
            model_a.create({
                'user_id': self.user_a.id,
                'name': 'Forged device',
            })


@tagged('post_install', '-at_install')
class TestMobileAuthHttp(common.HttpCase):
    """HTTP-контракт /streams/mobile/v1/auth/* и /push/register.

    Клиент шлёт стандартный JSON-RPC 2.0 конверт (type='jsonrpc');
    ошибки бизнес-уровня приходят в result: {'error': {'code', 'message'}}.
    TOTP-сценарий намеренно не поднимается (заведение totp_secret в тестах
    хрупко): проверяется только, что без включённого MFA totp_code не нужен.
    """

    PASSWORD = 'StreamsMobile!42'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Streams Mobile Http User',
            'login': 'streams.mobile.http@example.com',
            'password': cls.PASSWORD,
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    # ------------------------------------------------------------
    # Хелперы
    # ------------------------------------------------------------

    def _rpc(self, url, params=None, token=None):
        headers = {'Authorization': 'Bearer %s' % token} if token else None
        response = self.url_open(url, json={
            'jsonrpc': '2.0',
            'method': 'call',
            'params': params or {},
            'id': 1,
        }, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn(
            'error', data,
            'исключений быть не должно, ошибки едут в result: %s'
            % data.get('error'))
        return data.get('result')

    def _login(self, **overrides):
        params = {
            'login': self.user.login,
            'password': self.PASSWORD,
            'device_name': 'Pixel 9 Pro',
            'platform': 'android',
            'app_version': '1.0.0',
        }
        params.update(overrides)
        return self._rpc('/streams/mobile/v1/auth/login', params)

    def _device(self, device_id):
        return self.env['streams.mobile.device'].with_context(
            active_test=False).browse(device_id)

    # 8a
    def test_login_success_without_mfa(self):
        result = self._login()
        self.assertNotIn(
            'error', result,
            'без включённого MFA totp_code не требуется: %s' % (result,))
        self.assertTrue(result.get('token'))
        self.assertTrue(result.get('device_id'))
        self.assertEqual(result.get('user'), {
            'id': self.user.id,
            'name': self.user.name,
            'partner_id': self.user.partner_id.id,
        })

        self.env.invalidate_all()
        device = self._device(result['device_id'])
        self.assertTrue(device.exists())
        self.assertEqual(device.user_id, self.user)
        self.assertEqual(device.name, 'Pixel 9 Pro')
        self.assertEqual(device.platform, 'android')
        self.assertEqual(
            self.env['streams.mobile.device']._streams_from_token(
                result['token']),
            device, 'выданный по HTTP токен валиден для Bearer-проверки')

    # 8b
    def test_login_wrong_password(self):
        with mute_logger('odoo.addons.base.models.res_users'):
            result = self._login(password='wrong-password')
        self.assertEqual(
            (result.get('error') or {}).get('code'), 'auth_failed',
            'неверный пароль — машинный код auth_failed: %s' % (result,))
        self.assertNotIn('token', result)

    # 8c
    def test_logout_revokes_token(self):
        login = self._login()
        token = login['token']
        result = self._rpc(
            '/streams/mobile/v1/auth/logout', {}, token=token)
        self.assertTrue(result.get('ok'), 'logout отвечает ok: %s' % (result,))

        self.env.invalidate_all()
        device = self._device(login['device_id'])
        self.assertFalse(device.active, 'устройство архивировано')
        self.assertFalse(
            self.env['streams.mobile.device']._streams_from_token(token),
            'после logout токен погашен')

        result = self._rpc(
            '/streams/mobile/v1/auth/logout', {}, token=token)
        self.assertEqual(
            (result.get('error') or {}).get('code'), 'auth_failed',
            'повторный logout по погашенному токену — auth_failed')

    # 8d
    def test_push_register(self):
        login = self._login()
        token = login['token']
        result = self._rpc('/streams/mobile/v1/push/register', {
            'push_token': 'fcm-registration-token',
            'push_enabled': True,
        }, token=token)
        self.assertTrue(result.get('ok'), '%s' % (result,))

        self.env.invalidate_all()
        device = self._device(login['device_id'])
        self.assertEqual(device.push_token, 'fcm-registration-token')
        self.assertTrue(device.push_enabled)

        result = self._rpc('/streams/mobile/v1/push/register', {
            'push_enabled': False,
        }, token=token)
        self.assertTrue(result.get('ok'))
        self.env.invalidate_all()
        self.assertFalse(
            device.push_token, 'регистрация без токена очищает push_token')
        self.assertFalse(device.push_enabled)

        result = self._rpc('/streams/mobile/v1/push/register', {
            'push_token': 'x',
        })
        self.assertEqual(
            (result.get('error') or {}).get('code'), 'auth_failed',
            'без Bearer-заголовка регистрация недоступна')
