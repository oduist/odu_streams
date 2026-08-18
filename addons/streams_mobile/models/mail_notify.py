# -*- encoding: utf-8 -*-
import logging

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class MailNotify(models.Model):
    """Пуш на уведомление: всегда и всем получателям (политика ТЗ)."""
    _inherit = 'mail.notify'

    def _streams_broadcast_new(self):
        result = super()._streams_broadcast_new()
        try:
            self._streams_mobile_push_new()
        except Exception:
            # доставка пуша не должна ронять отправку уведомления
            _logger.exception(
                'streams_mobile: не удалось поставить пуш уведомления %s',
                self.id)
        return result

    def _streams_mobile_push_new(self):
        self.ensure_one()
        notify = self.sudo()
        partners = notify.recipient_ids.mapped('partner_id')
        if not partners:
            return
        body = html2plaintext(notify.body or '') or (
            'Voice message' if notify.voice_attachment_id else '')
        self.env['streams.mobile.push']._streams_enqueue(
            partners,
            title=notify.author_id.name or 'Notification',
            body=body,
            data={
                'type': 'notify',
                'notify_id': notify.id,
                'res_model': notify.res_model or False,
                'res_id': notify.res_id or False,
                'is_sticky': notify.is_sticky,
            })
