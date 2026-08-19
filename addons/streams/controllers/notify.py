# -*- encoding: utf-8 -*-
"""Загрузка вложений композера уведомлений (§12.2, разрыв G4 фазы 8).

Почему свой маршрут, а не ядровый `/mail/attachment/upload`.

Ядровый контроллер 19 (`mail/controllers/attachment.py`) сначала
резолвит тред — `_get_thread_with_access_for_post(thread_model, thread_id)`
— и без него отвечает 404; подмена `res_model='mail.compose.message'`,
`res_id=0` происходит уже потом, под флагом `is_pending`. Композер
уведомления треда не имеет вовсе: `mail.notify` — не `mail.thread`, а
приём клиента 15 (`thread_model='mail.notify'`, `thread_id=0`) в 19
гарантированно даёт 404.

Поэтому здесь ровно та часть ядрового маршрута, которая нам нужна:
создать pending-вложение текущего пользователя в том же виде, какого
ждёт серверная перепривязка `mail.notify._streams_bind_attachments`
(`res_model='mail.compose.message'`, `res_id=0`, `create_uid == uid`).
Образец — мобильный `streams_mobile/controllers/api.py` (upload).
"""
import logging

from odoo import http, _
from odoo.http import request

from odoo.addons.streams.models.mail_notify import MAX_VOICE_SIZE

_logger = logging.getLogger(__name__)

# Предел размера вложения композера уведомления. Совпадает с лимитом
# голосового сообщения (§12.3): больше 25 МБ в уведомлении не нужно
# никому, а OpenAI всё равно не примет.
MAX_NOTIFY_UPLOAD_BYTES = MAX_VOICE_SIZE


class StreamsNotifyController(http.Controller):
    """Вложения композера уведомлений."""

    @http.route('/streams/notify/attachment/upload', type='http',
                auth='user', methods=['POST'])
    def streams_notify_attachment_upload(self, ufile=None, **kwargs):
        """Залить pending-вложение и вернуть его плоское описание.

        Ответ намеренно плоский (`{id, name, mimetype, size}`), а не
        Store-образный: композер уведомления — свой OWL-диалог, записи
        `ir.attachment` в Store ему не нужны, а серверный payload
        уведомления (`_streams_payload`) описывает вложения ровно так же.
        """
        if request.env.user.share:
            # уведомления — инструмент внутренних (§12.2)
            return request.make_json_response(
                {'error': _("You are not allowed to upload here.")},
                status=403)
        if ufile is None or not getattr(ufile, 'filename', None):
            return request.make_json_response(
                {'error': _("No file was received.")}, status=400)
        data = ufile.read()
        if len(data) > MAX_NOTIFY_UPLOAD_BYTES:
            return request.make_json_response(
                {'error': _("The file is too large (25 MB max).")}, status=413)
        name = (ufile.filename or 'file').replace('/', '_').replace(
            '\\', '_').strip()[:255] or 'file'
        # sudo как в ядровом маршруте: `sudo()` поднимает только права, а
        # `create_uid` остаётся текущим пользователем — именно по нему
        # сверяется перепривязка `_streams_bind_attachments`
        attachment = request.env['ir.attachment'].sudo().create({
            'name': name,
            'raw': data,
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        attachment._post_add_create()
        _logger.debug(
            'streams: pending-вложение %s (%s) для композера уведомления',
            attachment.id, name)
        return request.make_json_response({
            'id': attachment.id,
            'name': attachment.name,
            'mimetype': attachment.mimetype or '',
            'size': attachment.file_size,
        })
