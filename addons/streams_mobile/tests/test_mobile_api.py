# -*- encoding: utf-8 -*-
"""Контракты API v1 (§3 design-phase6).

Два уровня:

* TransactionCase — серверные инварианты форматтера и poll-ключа
  (bus-записи создаются на precommit, поэтому перед проверками
  вызывается ``env.cr.precommit.run()``);
* HttpCase — «живой» проход login → init → channels → messages → post →
  mark_read → poll и негативные сценарии кодов ошибок. Каждый
  HTTP-запрос — отдельная транзакция, precommit там гоняет сам сервер.
"""
import json

from odoo.addons.bus.models.bus import channel_with_db, json_dump
from odoo.addons.streams_mobile.controllers.api import _format_message
from odoo.tests import common, tagged

MESSAGE_KEYS = {
    'id', 'body', 'date', 'kind', 'author', 'attachments', 'tracking',
    'reactions', 'parent_id',
}


@tagged('post_install', '-at_install')
class TestMobileApiFormat(common.TransactionCase):
    """Форматтер сообщения и сериализация bus-канала."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Mobile Format User',
            'login': 'mobile.format@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.record = cls.env['res.partner'].create({
            'name': 'Mobile Format Record',
            'email': 'format.record@example.com',
        })

    def _flush_tracking(self):
        """Трекинг в 19 отложен до precommit — без него сообщения нет."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def test_tracking_only_by_field_rights(self):
        """Поле с groups= скрыто из tracking для обычного пользователя."""
        self.record.write({'email': 'format.changed@example.com'})
        self._flush_tracking()
        message = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'),
            ('res_id', '=', self.record.id),
            ('message_type', '=', 'notification'),
        ], order='id desc', limit=1)
        self.assertTrue(message, 'write должен был создать change-сообщение')
        self.assertEqual(message._streams_classify(), 'change')
        # подкладываем tracking-значение поля, закрытого group_system
        protected = self.env['ir.model.fields']._get(
            'streams.mobile.device', 'token_hash')
        self.env['mail.tracking.value'].sudo().create({
            'field_id': protected.id,
            'old_value_char': 'old-hash',
            'new_value_char': 'new-hash',
            'mail_message_id': message.id,
        })
        data = _format_message(
            self.env['mail.message'].with_user(self.user).browse(message.id))
        self.assertEqual(data['kind'], 'change')
        self.assertLessEqual(MESSAGE_KEYS, set(data))
        names = [value['field'] for value in data['tracking']]
        self.assertIn('email', names, 'открытое поле должно отдаваться')
        self.assertNotIn(
            'token_hash', names,
            'поле с groups=base.group_system не должно утекать пользователю')
        email_value = next(
            value for value in data['tracking'] if value['field'] == 'email')
        self.assertEqual(email_value['new'], 'format.changed@example.com')
        # администратору защищённое поле видно — фильтр именно про права
        admin_data = _format_message(
            self.env['mail.message'].browse(message.id))
        admin_names = [value['field'] for value in admin_data['tracking']]
        self.assertIn('token_hash', admin_names)

    def test_non_change_message_has_no_tracking(self):
        message = self.record.with_user(self.user).message_post(
            body='plain comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        data = _format_message(
            self.env['mail.message'].with_user(self.user).browse(message.id))
        self.assertEqual(data['kind'], 'comment')
        self.assertIsNone(data['tracking'])
        self.assertIn('plain comment', data['body'])
        self.assertEqual(data['author']['id'], self.user.partner_id.id)

    def test_poll_channel_key_matches_core(self):
        """Ключ канала в /v1/poll строится ровно как ядровый `_sendone`."""
        partner = self.user.partner_id
        partner._bus_send('streams.mobile.test/ping', {'x': 1})
        # bus-записи создаются на precommit
        self.env.cr.precommit.run()
        key = json_dump(channel_with_db(self.env.cr.dbname, partner))
        row = self.env['bus.bus'].sudo().search([
            ('channel', '=', key)], order='id desc', limit=1)
        self.assertTrue(
            row, 'ключ канала обязан совпадать с ядровой сериализацией')
        payload = json.loads(row.message)
        self.assertEqual(payload['type'], 'streams.mobile.test/ping')
        self.assertEqual(payload['payload'], {'x': 1})


@tagged('post_install', '-at_install')
class TestMobileApiHttp(common.HttpCase):
    """Живой проход API по HTTP с Bearer-токенами."""

    PASSWORD = 'StreamsMobile#2026'
    BASE = '/streams/mobile/v1'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        cls.user_alice = cls.env['res.users'].create({
            'name': 'Mobile Alice',
            'login': 'mobile.alice@example.com',
            'password': cls.PASSWORD,
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.user_bob = cls.env['res.users'].create({
            'name': 'Mobile Bob',
            'login': 'mobile.bob@example.com',
            'password': cls.PASSWORD,
            'group_ids': [(6, 0, [group_user.id])],
        })
        # канал записи с обоими участниками: подписка + первый комментарий
        cls.record = cls.env['res.partner'].create({
            'name': 'Mobile API Record',
            'email': 'mobile.record@example.com',
        })
        cls.record.message_subscribe(partner_ids=[
            cls.user_alice.partner_id.id, cls.user_bob.partner_id.id])
        cls.record.with_user(cls.user_alice).message_post(
            body='seed comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        cls.channel = cls.env['discuss.channel'].sudo().search([
            ('channel_kind', '=', 'record'),
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', cls.record.id),
        ])
        # чужой канал: Алиса не участник
        cls.private_channel = cls.env['discuss.channel'].sudo().create({
            'name': 'Bob private group',
            'channel_type': 'group',
            'channel_member_ids': [
                (0, 0, {'partner_id': cls.user_bob.partner_id.id})],
        })
        # личный канал Changes Алисы
        cls.changes_channel = cls.env[
            'discuss.channel']._streams_get_changes_channel(cls.user_alice)
        cls.field_email = cls.env['ir.model.fields']._get(
            'res.partner', 'email')
        # bus-записи и трекинг материализуются на precommit
        cls.env.flush_all()
        cls.env.cr.precommit.run()

    # ------------------------------------------------------------
    # ХЕЛПЕРЫ
    # ------------------------------------------------------------

    def _rpc(self, path, params, token=None, check_error=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer %s' % token
        response = self.url_open(
            self.BASE + path,
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'id': 1,
                'params': params,
            }),
            headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json().get('result')
        if check_error:
            self.assertIsInstance(result, dict, result)
            self.assertNotIn(
                'error', result, '%s: неожиданная ошибка %s' % (path, result))
        return result

    def _error_code(self, result):
        self.assertIsInstance(result, dict, result)
        self.assertIn('error', result, result)
        return result['error']['code']

    def _login(self, user):
        result = self._rpc('/auth/login', {
            'login': user.login,
            'password': self.PASSWORD,
            'device_name': 'Test Device',
            'platform': 'android',
            'app_version': '1.0.0',
        })
        self.assertIn('token', result)
        self.assertEqual(result['user']['id'], user.id)
        return result['token']

    def _flush_tracking(self):
        self.env.flush_all()
        self.env.cr.precommit.run()

    # ------------------------------------------------------------
    # СЦЕНАРИИ
    # ------------------------------------------------------------

    def test_01_full_flow(self):
        """login → init → channels → messages → post → mark_read → poll."""
        # без токена — auth_failed
        self.assertEqual(
            self._error_code(self._rpc('/init', {}, check_error=False)),
            'auth_failed')
        token = self._login(self.user_alice)

        init = self._rpc('/init', {}, token)
        self.assertEqual(init['user'], {
            'id': self.user_alice.id,
            'name': self.user_alice.name,
            'partner_id': self.user_alice.partner_id.id,
        })
        self.assertLessEqual(
            {'counter', 'channel_id', 'default_timeout', 'pending'},
            set(init['notify']))
        self.assertIn('unread_total', init)
        self.assertIn('server_time', init)
        self.assertFalse(
            init['filters_defaults']['change'],
            'change по умолчанию скрыт (§6)')

        channels = self._rpc('/channels', {}, token)['channels']
        entry = next(
            channel for channel in channels
            if channel['res_model'] == 'res.partner'
            and channel['res_id'] == self.record.id)
        self.assertEqual(entry['kind'], 'record')
        self.assertIn('unread', entry)
        self.assertGreaterEqual(entry['members_count'], 2)
        self.assertTrue(entry['last_message'])
        self.assertLessEqual(MESSAGE_KEYS, set(entry['last_message']))

        messages = self._rpc(
            '/channel/messages', {'channel_id': self.channel.id},
            token)['messages']
        self.assertTrue(messages)
        self.assertLessEqual(MESSAGE_KEYS, set(messages[0]))
        seed = next(
            message for message in messages
            if 'seed comment' in message['body'])
        self.assertEqual(seed['kind'], 'comment')
        self.assertEqual(seed['author']['id'], self.user_alice.partner_id.id)

        posted = self._rpc('/channel/post', {
            'channel_id': self.channel.id,
            'body': 'from mobile',
            'kind': 'comment',
        }, token)
        self.assertEqual(posted['kind'], 'comment')
        self.assertIn('from mobile', posted['body'])
        self.assertEqual(posted['author']['id'], self.user_alice.partner_id.id)
        # reverse-post: сообщение легло на запись и видно в чаттере
        record_message = self.env['mail.message'].sudo().browse(posted['id'])
        self.assertEqual(record_message.model, 'res.partner')
        self.assertEqual(record_message.res_id, self.record.id)

        mark = self._rpc('/channel/mark_read', {
            'channel_id': self.channel.id,
            'last_message_id': posted['id'],
        }, token)
        self.assertTrue(mark['ok'])
        self.assertEqual(mark['unread'], 0)

        # у второго участника пост лежит в шине как new_message
        token_bob = self._login(self.user_bob)
        poll = self._rpc('/poll', {'last_bus_id': 0}, token_bob)
        self.assertGreater(poll['last_bus_id'], 0)
        self.assertTrue(
            any(notification['type'] == 'discuss.channel/new_message'
                and (notification['payload'] or {}).get('id')
                == self.channel.id
                for notification in poll['notifications']),
            'участник должен получить discuss.channel/new_message: %s'
            % poll['notifications'])
        # повторный poll с возвращённым last_bus_id пуст
        again = self._rpc(
            '/poll', {'last_bus_id': poll['last_bus_id']}, token_bob)
        self.assertEqual(again['notifications'], [])
        self.assertGreaterEqual(again['last_bus_id'], poll['last_bus_id'])

    def test_02_foreign_channel_access_denied(self):
        token = self._login(self.user_alice)
        result = self._rpc(
            '/channel/messages', {'channel_id': self.private_channel.id},
            token, check_error=False)
        self.assertEqual(self._error_code(result), 'access_denied')
        result = self._rpc('/channel/post', {
            'channel_id': self.private_channel.id,
            'body': 'sneaky', 'kind': 'comment',
        }, token, check_error=False)
        self.assertEqual(self._error_code(result), 'access_denied')
        result = self._rpc('/channel/messages', {'channel_id': 999999999},
                           token, check_error=False)
        self.assertEqual(self._error_code(result), 'not_found')

    def test_03_changes_channel_and_feed(self):
        token = self._login(self.user_alice)
        # лента Changes не отдаётся через /channel/messages
        result = self._rpc(
            '/channel/messages', {'channel_id': self.changes_channel.id},
            token, check_error=False)
        self.assertEqual(self._error_code(result), 'bad_request')
        # подписка на поле через API
        subscription = self._rpc('/fields/subscription', {
            'res_model': 'res.partner', 'res_id': self.record.id,
        }, token)
        self.assertIn('available_fields', subscription)
        set_result = self._rpc('/fields/subscription', {
            'res_model': 'res.partner', 'res_id': self.record.id,
            'field_ids': [self.field_email.id],
        }, token)
        self.assertTrue(set_result['subscribed'])
        self.assertIn(self.field_email.id, set_result['field_ids'])
        # изменение подписанного поля попадает в ленту Changes
        self.record.write({'email': 'mobile.changed@example.com'})
        self._flush_tracking()
        feed = self._rpc('/changes/feed', {}, token)
        self.assertEqual(feed['channel_id'], self.changes_channel.id)
        self.assertTrue(feed['items'], 'лента Changes не должна быть пустой')
        item = feed['items'][0]
        self.assertEqual(item['res_model'], 'res.partner')
        self.assertEqual(item['res_id'], self.record.id)
        self.assertTrue(any(
            value['field_name'] == 'email'
            for change in item['changes'] for value in change['values']))

    def test_04_channel_filters(self):
        token = self._login(self.user_alice)
        current = self._rpc(
            '/channel/filters', {'channel_id': self.channel.id}, token)
        self.assertFalse(current['filters']['change'])
        updated = self._rpc('/channel/filters', {
            'channel_id': self.channel.id,
            'filters': {'change': True},
        }, token)
        self.assertTrue(updated['filters']['change'])
        # персистентность
        again = self._rpc(
            '/channel/filters', {'channel_id': self.channel.id}, token)
        self.assertTrue(again['filters']['change'])

    def test_05_notify_wrappers(self):
        token_alice = self._login(self.user_alice)
        token_bob = self._login(self.user_bob)
        # пустые получатели — bad_request
        result = self._rpc('/notify/send', {'body': 'no one'},
                           token_alice, check_error=False)
        self.assertEqual(self._error_code(result), 'bad_request')
        sent = self._rpc('/notify/send', {
            'body': 'mobile ping',
            'user_ids': [self.user_bob.id],
        }, token_alice)
        self.assertIn('id', sent)
        feed = self._rpc('/notify/feed', {'box': 'received'},
                         token_bob)['items']
        received = next(
            item for item in feed if item['id'] == sent['id'])
        self.assertIn('mobile ping', received['body'])
        self.assertFalse(received['read_date'])
        marked = self._rpc(
            '/notify/mark_read', {'notify_ids': [sent['id']]}, token_bob)
        self.assertIn('counter', marked)
        shown = self._rpc(
            '/notify/popup_shown', {'notify_ids': [sent['id']]}, token_bob)
        self.assertTrue(shown['ok'])
        replied = self._rpc('/notify/reply', {
            'parent_id': sent['id'], 'body': 'mobile pong',
        }, token_bob)
        self.assertIn('id', replied)
        sent_box = self._rpc('/notify/feed', {'box': 'sent'},
                             token_alice)['items']
        self.assertTrue(any(item['id'] == sent['id'] for item in sent_box))

    def test_06_attachment_upload_and_download(self):
        token_alice = self._login(self.user_alice)
        headers = {'Authorization': 'Bearer %s' % token_alice}
        # без токена — 401
        response = self.url_open(
            self.BASE + '/attachment/upload',
            files={'ufile': ('note.txt', b'mobile upload', 'text/plain')})
        self.assertEqual(response.status_code, 401)
        # загрузка — pending-паттерн композера
        response = self.url_open(
            self.BASE + '/attachment/upload',
            files={'ufile': ('note.txt', b'mobile upload', 'text/plain')},
            headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['name'], 'note.txt')
        self.assertEqual(data['size'], len(b'mobile upload'))
        attachment = self.env['ir.attachment'].sudo().browse(data['id'])
        self.assertEqual(attachment.res_model, 'mail.compose.message')
        self.assertEqual(attachment.res_id, 0)
        self.assertEqual(attachment.create_uid, self.user_alice)
        # своё pending-вложение отдаётся
        response = self.url_open(
            '%s/attachment/%s' % (self.BASE, data['id']), headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'mobile upload')
        # чужое pending-вложение — 404
        foreign = self.env['ir.attachment'].with_user(
            self.user_bob).create({
                'name': 'bob.txt',
                'raw': b'bob secret',
                'res_model': 'mail.compose.message',
                'res_id': 0,
            })
        self.env.flush_all()
        response = self.url_open(
            '%s/attachment/%s' % (self.BASE, foreign.id), headers=headers)
        self.assertEqual(response.status_code, 404)
        # несуществующее — 404
        response = self.url_open(
            '%s/attachment/999999999' % self.BASE, headers=headers)
        self.assertEqual(response.status_code, 404)
