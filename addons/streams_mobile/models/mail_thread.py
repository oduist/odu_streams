# -*- encoding: utf-8 -*-
import logging

from odoo import models
from odoo.tools import html2plaintext

from odoo.addons.streams.models.mail_message import (
    STREAM_COMMENT, STREAM_MESSAGE, STREAM_NOTE)

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    """Пуши проекций записи по политике потоков (§4 design-phase6):

    * comment / message — участникам канала, кроме автора;
    * note — только явно упомянутым;
    * change / activity — никогда.

    ACL как у шины: получатель без права чтения записи не получает и пуш
    (тот же `_streams_readable_partners`, что фильтрует bus-доставку).
    """
    _inherit = 'mail.thread'

    def _streams_broadcast(self, channel, message):
        result = super()._streams_broadcast(channel, message)
        try:
            self._streams_mobile_push(channel, message)
        except Exception:
            # пуш не должен ронять публикацию сообщения
            _logger.exception(
                'streams_mobile: не удалось поставить пуш сообщения %s',
                message.id)
        return result

    def _streams_mobile_push(self, channel, message):
        self.ensure_one()
        message_sudo = message.sudo()
        stream = message_sudo._streams_classify()
        if stream not in (STREAM_COMMENT, STREAM_MESSAGE, STREAM_NOTE):
            # change и activity пушей не порождают никогда
            return
        author = message_sudo.author_id
        if stream == STREAM_NOTE:
            # заметка: единственный триггер — явное упоминание
            recipients = message_sudo.partner_ids
        else:
            recipients = channel.sudo().channel_partner_ids
        recipients = recipients - author
        if not recipients:
            return
        recipients = self._streams_readable_partners(recipients)
        if not recipients:
            return
        record_name = self.sudo().display_name or channel.sudo().name or ''
        self.env['streams.mobile.push']._streams_enqueue(
            recipients,
            title='%s — %s' % (record_name, author.name or ''),
            body=html2plaintext(message_sudo.body or ''),
            data={
                'type': 'message',
                'kind': stream,
                'channel_id': channel.id,
                'message_id': message.id,
                'res_model': self._name,
                'res_id': self.id,
            })
