# -*- encoding: utf-8 -*-
import base64
import json
from unittest.mock import patch

from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import common, tagged
from odoo.tools import mute_logger

from odoo.addons.streams.models import mail_notify


class FakeResponse:
    """Заглушка ответа OpenAI: транскрипцию живьём в тестах не дёргаем."""

    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


@tagged('post_install', '-at_install')
class TestStreamsNotify(common.TransactionCase):
    """Приоритетные уведомления (§4.5, §12)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tag = cls.env['res.partner.category'].create({
            'name': 'Streams Notify Tag'})
        cls.country = cls.env.ref('base.pl')
        group_user = cls.env.ref('base.group_user')
        cls.author = cls.env['res.users'].create({
            'name': 'Streams Notify Author',
            'login': 'streams.notify.author@example.com',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.receiver = cls.env['res.users'].create({
            'name': 'Streams Notify Receiver',
            'login': 'streams.notify.receiver@example.com',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.stranger = cls.env['res.users'].create({
            'name': 'Streams Notify Stranger',
            'login': 'streams.notify.stranger@example.com',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.portal_user = cls.env['res.users'].create({
            'name': 'Streams Notify Portal',
            'login': 'streams.notify.portal@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })

    # ------------------------------------------------------------
    # Хелперы
    # ------------------------------------------------------------

    @classmethod
    def _make_partner(cls, name):
        return cls.env['res.partner'].create({
            'name': name,
            'country_id': cls.country.id,
            'category_id': [(6, 0, [cls.tag.id])],
        })

    def _notify_model(self, user):
        return self.env['mail.notify'].with_user(user)

    def _send(self, user, **vals):
        vals.setdefault('body', 'Hello')
        result = self._notify_model(user).streams_notify_send(vals)
        return self.env['mail.notify'].sudo().browse(result['id'])

    def _rows(self, notify):
        return notify.sudo().recipient_ids

    def _row(self, notify, user):
        return self._rows(notify).filtered(
            lambda row: row.user_id == user)

    def _flush_bus(self):
        """19: записи `bus.bus` создаются на precommit — без него шина пуста."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _last_bus_id(self):
        self._flush_bus()
        last = self.env['bus.bus'].sudo().search([], order='id desc', limit=1)
        return last.id or 0

    def _bus_since(self, bus_id):
        """Сообщения шины после указанного id: [(channel, type, payload)].

        19: channel — JSON-строка ["<db>", "res.partner", <partner_id>]:
        уведомления адресуются партнёру получателя; message — JSON
        {"type": ..., "payload": ...}.
        """
        self._flush_bus()
        records = self.env['bus.bus'].sudo().search([('id', '>', bus_id)])
        result = []
        for record in records:
            message = json.loads(record.message)
            result.append((
                json.loads(record.channel),
                message.get('type'),
                message.get('payload'),
            ))
        return result

    def _make_attachment(self, user, name='voice.webm',
                         mimetype='audio/webm', pending=True):
        values = {
            'name': name,
            'datas': base64.b64encode(b'fake-audio-payload'),
            'mimetype': mimetype,
        }
        if pending:
            values.update({'res_model': 'mail.compose.message', 'res_id': 0})
        return self.env['ir.attachment'].with_user(user).create(values)

    def _notify_channel(self, user, create=False):
        return self.env['discuss.channel']._streams_get_notifications_channel(
            user, create=create)

    def _unread_counter(self, channel, user):
        """19: счётчик непрочитанного живёт на `discuss.channel.member`,
        а не на канале; считается для владельца — читаем от его лица."""
        member = self.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', user.partner_id.id),
        ], limit=1)
        self.assertTrue(member, 'владелец — участник своего личного канала')
        member = member.with_user(user)
        member.invalidate_recordset(['message_unread_counter'])
        return member.message_unread_counter

    def _init_messaging_payload(self, user):
        """19: `_init_messaging(store)` наполняет Store; наш payload лежит
        в глобальных значениях синглтона 'Store'."""
        store = Store()
        user.with_user(user)._init_messaging(store)
        return store.get_result()['Store']['streams_notify']

    # ------------------------------------------------------------
    # 1
    # ------------------------------------------------------------
    @mute_logger('odoo.addons.base.models.ir_rule', 'odoo.models')
    def test_01_send_creates_recipients_and_access(self):
        notify = self._send(self.author, user_ids=[self.receiver.id])

        self.assertEqual(self._rows(notify).mapped('user_id'), self.receiver)
        self.assertEqual(notify.author_id, self.author)
        self.assertEqual(
            self._rows(notify).partner_id, self.receiver.partner_id,
            'partner_id получателя хранится для адресации и аватара')

        # автор и получатель читают уведомление
        self.assertTrue(notify.with_user(self.author).body)
        self.assertTrue(notify.with_user(self.receiver).body)
        # посторонний — нет
        with self.assertRaises(AccessError):
            notify.with_user(self.stranger).read(['body'])

    # ------------------------------------------------------------
    # 2
    # ------------------------------------------------------------
    @mute_logger('odoo.addons.base.models.ir_rule', 'odoo.models')
    def test_02_recipient_may_only_mark_own_state(self):
        notify = self._send(self.author, user_ids=[self.receiver.id])
        row = self._row(notify, self.receiver)

        row.with_user(self.receiver).write({'popup_shown': True})
        self.assertTrue(row.popup_shown)

        with self.assertRaises(AccessError):
            row.with_user(self.receiver).write({'user_id': self.stranger.id})
        with self.assertRaises(AccessError):
            notify.with_user(self.receiver).write({'body': '<p>hacked</p>'})

        # автор своё уведомление правит
        notify.with_user(self.author).write({'body': '<p>fixed</p>'})
        self.assertEqual(notify.body, '<p>fixed</p>')

    # ------------------------------------------------------------
    # 3
    # ------------------------------------------------------------
    def test_03_voice_forces_sticky(self):
        voice = self._make_attachment(self.author)
        notify = self._send(
            self.author, user_ids=[self.receiver.id],
            voice_attachment_id=voice.id, voice_duration=12,
            is_sticky=False, timeout=5)

        self.assertTrue(
            notify.is_sticky,
            'голос форсирует sticky даже при is_sticky=False (§12.3)')
        self.assertEqual(notify.voice_duration, 12)

        notify.with_user(self.author).write({'is_sticky': False})
        self.assertTrue(
            notify.is_sticky, 'снять sticky с голосового нельзя')

        # запись браузера приезжает как video/webm: mimetype считает сервер
        # по имени файла, а stdlib знает `.webm` только как видео
        browser_voice = self._make_attachment(
            self.author, name='voice-20260818-120000.webm',
            mimetype='video/webm')
        recorded = self._send(
            self.author, user_ids=[self.receiver.id],
            voice_attachment_id=browser_voice.id, voice_duration=3)
        self.assertTrue(recorded.is_sticky)
        self.assertEqual(recorded.voice_attachment_id, browser_voice)

        # чужой формат по-прежнему отбрасывается
        document = self._make_attachment(
            self.author, name='notes.txt', mimetype='text/plain')
        with self.assertRaises(UserError):
            self._send(
                self.author, user_ids=[self.receiver.id],
                voice_attachment_id=document.id, voice_duration=3)

    # ------------------------------------------------------------
    # 4
    # ------------------------------------------------------------
    def test_04_timeout_default_and_clamp(self):
        notify = self._send(self.author, user_ids=[self.receiver.id])
        self.assertEqual(notify.timeout, 10, 'дефолт продукта — 10 секунд')

        self.env['ir.config_parameter'].sudo().set_param(
            mail_notify.NOTIFY_TIMEOUT_PARAM, '25')
        later = self._send(self.author, user_ids=[self.receiver.id])
        self.assertEqual(later.timeout, 25)

        clamped = self._send(
            self.author, user_ids=[self.receiver.id], timeout=5000)
        self.assertEqual(
            clamped.timeout, mail_notify.MAX_NOTIFY_TIMEOUT,
            'таймаут зажимается в допустимый диапазон')

    # ------------------------------------------------------------
    # 5
    # ------------------------------------------------------------
    @mute_logger('odoo.addons.base.models.ir_rule', 'odoo.models')
    def test_05_pending_attachments_are_rebound(self):
        attachment = self._make_attachment(
            self.author, name='spec.pdf', mimetype='application/pdf')
        notify = self._send(
            self.author, user_ids=[self.receiver.id],
            attachment_ids=[attachment.id])

        attachment.invalidate_recordset()
        self.assertEqual(attachment.sudo().res_model, 'mail.notify')
        self.assertEqual(attachment.sudo().res_id, notify.id)
        self.assertEqual(notify.attachment_ids, attachment)

        # доступ к файлу повторяет доступ к уведомлению
        self.assertTrue(attachment.with_user(self.receiver).read(['name']))
        with self.assertRaises(AccessError):
            attachment.with_user(self.stranger).read(['name'])

    # ------------------------------------------------------------
    # 6
    # ------------------------------------------------------------
    def test_06_reply_goes_to_parent_author_only(self):
        parent = self._send(
            self.author, user_ids=[self.receiver.id, self.stranger.id],
            is_sticky=True, timeout=42)

        result = self._notify_model(self.receiver).streams_notify_reply(
            parent.id, {'body': 'Got it'})
        reply = self.env['mail.notify'].sudo().browse(result['id'])

        self.assertEqual(
            self._rows(reply).mapped('user_id'), self.author,
            'ответ уходит только автору исходного (§12.6)')
        self.assertEqual(reply.parent_id, parent)
        self.assertTrue(reply.is_sticky, 'sticky наследуется')
        self.assertEqual(reply.timeout, 42, 'timeout наследуется')

        # переопределение работает
        override = self.env['mail.notify'].sudo().browse(
            self._notify_model(self.receiver).streams_notify_reply(
                parent.id, {'body': 'Again', 'is_sticky': False,
                            'timeout': 7})['id'])
        self.assertFalse(override.is_sticky)
        self.assertEqual(override.timeout, 7)

        # цепочка из трёх звеньев
        third = self.env['mail.notify'].sudo().browse(
            self._notify_model(self.author).streams_notify_reply(
                reply.id, {'body': 'And back'})['id'])
        self.assertEqual(third.parent_id, reply)
        self.assertEqual(third.parent_id.parent_id, parent)
        self.assertEqual(self._rows(third).mapped('user_id'), self.receiver)

    # ------------------------------------------------------------
    # 7
    # ------------------------------------------------------------
    def test_07_mark_read_is_written_once(self):
        notify = self._send(self.author, user_ids=[self.receiver.id])
        row = self._row(notify, self.receiver)
        self.assertFalse(row.read_date)

        self._notify_model(self.receiver).streams_notify_mark_read([notify.id])
        row.invalidate_recordset()
        first_read = row.read_date
        self.assertTrue(first_read)

        self._notify_model(self.receiver).streams_notify_mark_read([notify.id])
        row.invalidate_recordset()
        self.assertEqual(
            row.read_date, first_read, 'повтор не перетирает время прочтения')

        sent = self._notify_model(self.author).streams_notify_feed(box='sent')
        item = [entry for entry in sent if entry['id'] == notify.id][0]
        self.assertTrue(
            item['recipients'][0]['read_date'],
            'автор видит время прочтения (§12.5)')

    # ------------------------------------------------------------
    # 8
    # ------------------------------------------------------------
    def test_08_counter_and_channel_unread(self):
        notify_model = self._notify_model(self.receiver)
        first = self._send(self.author, user_ids=[self.receiver.id])
        second = self._send(self.author, user_ids=[self.receiver.id])
        self.assertEqual(notify_model._streams_notify_counter(), 2)

        channel = self._notify_channel(self.receiver)
        self.assertTrue(channel, 'канал получателя создан при отправке')
        # 19: message_unread_counter переехал с канала на участника
        self.assertEqual(self._unread_counter(channel, self.receiver), 2)

        notify_model.streams_notify_mark_read([first.id, second.id])
        self.assertEqual(notify_model._streams_notify_counter(), 0)
        self.assertEqual(self._unread_counter(channel, self.receiver), 0)

    # ------------------------------------------------------------
    # 9
    # ------------------------------------------------------------
    def test_09_pending_popups_in_init_messaging(self):
        notify = self._send(self.author, user_ids=[self.receiver.id])
        # 19: _init_messaging наполняет Store, а не возвращает dict
        payload = self._init_messaging_payload(self.receiver)

        self.assertEqual(payload['counter'], 1)
        self.assertTrue(payload['channel_id'])
        self.assertEqual([item['id'] for item in payload['pending']],
                         [notify.id])

        self._notify_model(self.receiver).streams_notify_popup_shown(
            [notify.id])
        payload = self._init_messaging_payload(self.receiver)
        self.assertFalse(
            payload['pending'],
            'показанный попап второй раз не всплывает')

    # ------------------------------------------------------------
    # 10
    # ------------------------------------------------------------
    def test_10_notify_stays_out_of_streams(self):
        partner = self._make_partner('Streams Notify Isolation')
        messages_before = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id)])

        notify = self._send(
            self.author, user_ids=[self.receiver.id],
            res_model='res.partner', res_id=partner.id)

        self.assertEqual(notify.record_name, partner.display_name)
        messages_after = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id)])
        self.assertEqual(
            messages_before, messages_after,
            'уведомление не создаёт mail.message на записи (§12.1)')
        self.assertFalse(
            self.env['discuss.channel'].sudo().with_context(
                active_test=False).search([
                    ('channel_kind', '=', 'record'),
                    ('res_model', '=', 'res.partner'),
                    ('res_id', '=', partner.id),
                ]),
            'уведомление не создаёт канал записи')

    # ------------------------------------------------------------
    # 11
    # ------------------------------------------------------------
    def test_11_share_recipient_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._send(self.author, user_ids=[self.portal_user.id])
        with self.assertRaises(UserError):
            self._send(self.author, user_ids=[])

    # ------------------------------------------------------------
    # 12
    # ------------------------------------------------------------
    def test_12_transcription(self):
        config = self.env['ir.config_parameter'].sudo()

        # ключа нет — задание не ставится, состояние остаётся none
        config.set_param(mail_notify.OPENAI_API_KEY_PARAM, '')
        voice = self._make_attachment(self.author)
        silent = self._send(
            self.author, user_ids=[self.receiver.id],
            voice_attachment_id=voice.id, voice_duration=5)
        self.assertEqual(silent.transcript_state, 'none')

        # ключ есть — уведомление уходит в очередь
        config.set_param(mail_notify.OPENAI_API_KEY_PARAM, 'sk-test')
        voice = self._make_attachment(self.author)
        notify = self._send(
            self.author, user_ids=[self.receiver.id],
            voice_attachment_id=voice.id, voice_duration=5)
        self.assertEqual(notify.transcript_state, 'queued')
        self.assertTrue(
            self.env['queue.job'].sudo().search_count([
                ('identity_key', '=',
                 'streams.notify.transcript.%s' % notify.id)]),
            'задание транскрипции поставлено в очередь')

        # успех: текст и рассылка обновления по шине
        bus_id = self._last_bus_id()
        with patch.object(
                mail_notify.requests, 'post',
                return_value=FakeResponse(200, {'text': 'Hello there'})):
            notify._job_transcribe()
        self.assertEqual(notify.transcript, 'Hello there')
        self.assertEqual(notify.transcript_state, 'done')
        updates = [
            payload for _channel, msg_type, payload in self._bus_since(bus_id)
            if msg_type == mail_notify.BUS_UPDATE
        ]
        self.assertTrue(updates, 'обновление транскрипта ушло по шине')
        self.assertEqual(updates[0]['transcript'], 'Hello there')

        # 4xx: состояние failed, задание не ретраится
        voice = self._make_attachment(self.author)
        failing = self._send(
            self.author, user_ids=[self.receiver.id],
            voice_attachment_id=voice.id, voice_duration=5)
        with patch.object(
                mail_notify.requests, 'post',
                return_value=FakeResponse(400, text='bad request')):
            failing._job_transcribe()
        self.assertEqual(failing.transcript_state, 'failed')
        self.assertFalse(failing.transcript)

    # ------------------------------------------------------------
    # 13
    # ------------------------------------------------------------
    def test_13_notifications_channel_is_lazy_and_unique(self):
        self.assertFalse(
            self._notify_channel(self.receiver),
            'канал не заводится, пока уведомлений нет')

        self._send(self.author, user_ids=[self.receiver.id])
        channel = self._notify_channel(self.receiver)
        self.assertTrue(channel)
        self.assertEqual(channel.channel_kind, 'notifications')
        self.assertEqual(
            channel.channel_partner_ids, self.receiver.partner_id,
            'единственный участник личного канала — его владелец')

        again = self._notify_channel(self.receiver, create=True)
        self.assertEqual(again, channel, 'канал ровно один на пользователя')

        # у автора появился свой канал, и это другой канал
        author_channel = self._notify_channel(self.author)
        self.assertTrue(author_channel)
        self.assertNotEqual(author_channel, channel)

    # ------------------------------------------------------------
    # 14 — Mute (§12.4, решение пользователя)
    # ------------------------------------------------------------
    def test_14_sound_mute_setting(self):
        settings = self.env['res.users.settings']._find_or_create_for_user(
            self.receiver)
        self.assertFalse(settings.is_streams_notify_sound_muted)

        settings.with_user(self.receiver).set_res_users_settings(
            {'is_streams_notify_sound_muted': True})
        settings.invalidate_recordset()
        self.assertTrue(settings.is_streams_notify_sound_muted)

        formatted = settings._res_users_settings_format()
        self.assertTrue(
            formatted['is_streams_notify_sound_muted'],
            'флаг едет клиенту вместе со стартом (init_messaging)')

    # ------------------------------------------------------------
    # Лента и шина
    # ------------------------------------------------------------
    def test_15_feed_and_bus_payload(self):
        bus_id = self._last_bus_id()
        notify = self._send(
            self.author, user_ids=[self.receiver.id], body='Ping')

        received = self._notify_model(self.receiver).streams_notify_feed()
        item = [entry for entry in received if entry['id'] == notify.id][0]
        self.assertEqual(item['author']['id'], self.author.id)
        self.assertIn('Ping', item['body'])
        self.assertFalse(item['read_date'])

        news = [
            (channel, payload)
            for channel, msg_type, payload in self._bus_since(bus_id)
            if msg_type == mail_notify.BUS_NEW
        ]
        self.assertEqual(len(news), 1, 'получателю ушло ровно одно new')
        channel, payload = news[0]
        self.assertEqual(payload['id'], notify.id)
        self.assertEqual(payload['counter'], 1)
        self.assertEqual(
            channel[1:], ['res.partner', self.receiver.partner_id.id],
            'уведомление адресовано партнёру получателя')
