# -*- encoding: utf-8 -*-
import json
import logging

from odoo import models, fields, api

from .mail_message import STREAMS_FILTER_DEFAULTS

_logger = logging.getLogger(__name__)


class MailChannelPartner(models.Model):
    """Зеркало «участник канала → follower записи» (§5.3).

    Обратное направление (follower → участник) живёт в
    `mail.thread.message_subscribe`. От рекурсии обе стороны защищены
    контекстом `streams_sync`.
    """
    _inherit = 'mail.channel.partner'

    streams_filters = fields.Char(
        string='Stream Filters',
        help="Per-user display filters of the record channel, stored as JSON.")

    def _streams_get_filters(self):
        """Фильтры участника поверх дефолтов (§6).

        Хранится JSON, а не набор булевых полей: список потоков ещё будет
        расти, а миграция схемы ради флажка отображения не нужна.
        """
        self.ensure_one()
        filters = dict(STREAMS_FILTER_DEFAULTS)
        if not self.streams_filters:
            return filters
        try:
            stored = json.loads(self.streams_filters)
        except (TypeError, ValueError):
            _logger.warning(
                'streams: битые фильтры участника %s: %r',
                self.id, self.streams_filters)
            return filters
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in filters:
                    filters[key] = bool(value)
        return filters

    def _streams_set_filters(self, filters):
        """Дописать переданные потоки в фильтры участника."""
        self.ensure_one()
        current = self._streams_get_filters()
        for key, value in (filters or {}).items():
            if key in STREAMS_FILTER_DEFAULTS:
                current[key] = bool(value)
        self.sudo().write({'streams_filters': json.dumps(current)})
        return current

    @api.model_create_multi
    def create(self, vals_list):
        members = super().create(vals_list)
        members._streams_mirror_followers(subscribe=True)
        return members

    def unlink(self):
        self._streams_mirror_followers(subscribe=False)
        return super().unlink()

    def _streams_mirror_followers(self, subscribe=True):
        if self.env.context.get('streams_sync'):
            return
        partners_by_record = {}
        for member in self.sudo():
            channel = member.channel_id
            if channel.channel_kind != 'record':
                continue
            if not channel.res_model or not channel.res_id:
                continue
            if not member.partner_id:
                continue
            partners_by_record.setdefault(
                (channel.res_model, channel.res_id), set()).add(
                    member.partner_id.id)
        for (res_model, res_id), partner_ids in partners_by_record.items():
            if res_model not in self.env:
                continue
            record = self.env[res_model].sudo().with_context(
                active_test=False).browse(res_id).exists()
            if not record:
                continue
            record = record.with_context(streams_sync=True)
            if subscribe:
                record.message_subscribe(partner_ids=list(partner_ids))
            else:
                record.message_unsubscribe(partner_ids=list(partner_ids))
