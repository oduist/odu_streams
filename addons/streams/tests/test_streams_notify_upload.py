# -*- encoding: utf-8 -*-
import io
import json

from odoo import http
from odoo.tests import common, tagged

from odoo.addons.streams.controllers.notify import MAX_NOTIFY_UPLOAD_BYTES


@tagged('post_install', '-at_install')
class TestStreamsNotifyUpload(common.HttpCase):
    """Маршрут вложений композера уведомлений (разрыв G4 фазы 8).

    Ядровый `/mail/attachment/upload` в 19 требует существующий тред с
    правом постинга, а у композера уведомления треда нет вовсе. Здесь
    проверяется, что свой маршрут отдаёт вложение ровно в том виде,
    какого ждёт `mail.notify._streams_bind_attachments`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        cls.uploader = cls.env['res.users'].create({
            'name': 'Streams Upload Author',
            'login': 'streams.upload.author',
            'password': 'streams.upload.author',
            'group_ids': [(6, 0, [group_user.id])],
        })
        cls.receiver = cls.env['res.users'].create({
            'name': 'Streams Upload Receiver',
            'login': 'streams.upload.receiver',
            'group_ids': [(6, 0, [group_user.id])],
        })

    def _upload(self, content=b'hello', filename='note.txt'):
        """POST на маршрут от лица уже аутентифицированной сессии."""
        return self.url_open(
            '/streams/notify/attachment/upload',
            files={'ufile': (filename, io.BytesIO(content), 'text/plain')},
            # идиома ядровых тестов (mail/tests/common_controllers.py)
            data={'csrf_token': http.Request.csrf_token(self)},
        )

    def test_upload_creates_pending_attachment(self):
        """Вложение создаётся как pending-вложение композера."""
        self.authenticate('streams.upload.author', 'streams.upload.author')
        response = self._upload()
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload.get('id'))
        self.assertEqual(payload['name'], 'note.txt')
        self.assertEqual(payload['size'], 5)
        attachment = self.env['ir.attachment'].sudo().browse(payload['id'])
        self.assertEqual(attachment.res_model, 'mail.compose.message')
        self.assertEqual(attachment.res_id, 0)
        self.assertEqual(attachment.create_uid, self.uploader)

    def test_uploaded_attachment_binds_to_notification(self):
        """Отправка уведомления перепривязывает такое вложение к себе."""
        self.authenticate('streams.upload.author', 'streams.upload.author')
        payload = json.loads(self._upload().content)
        sent = self.env['mail.notify'].with_user(
            self.uploader).streams_notify_send({
                'user_ids': [self.receiver.id],
                'body': 'with attachment',
                'attachment_ids': [payload['id']],
            })
        notify = self.env['mail.notify'].sudo().browse(sent['id'])
        self.assertEqual(notify.attachment_ids.ids, [payload['id']])
        self.assertEqual(notify.attachment_ids.res_model, 'mail.notify')
        self.assertEqual(notify.attachment_ids.res_id, notify.id)

    def test_upload_rejects_oversized_file(self):
        """Слишком большой файл отбивается до создания вложения."""
        self.authenticate('streams.upload.author', 'streams.upload.author')
        before = self.env['ir.attachment'].sudo().search_count([])
        response = self._upload(
            content=b'x' * (MAX_NOTIFY_UPLOAD_BYTES + 1), filename='big.bin')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            self.env['ir.attachment'].sudo().search_count([]), before)

    def test_upload_requires_login(self):
        """Аноним на маршрут не проходит."""
        response = self.url_open(
            '/streams/notify/attachment/upload',
            files={'ufile': ('note.txt', io.BytesIO(b'hello'), 'text/plain')},
            allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)
