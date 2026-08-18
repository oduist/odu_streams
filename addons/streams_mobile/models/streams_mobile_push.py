# -*- encoding: utf-8 -*-
import json
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Payload FCM ограничен 4KB; тело обрезается с запасом на служебные ключи.
PUSH_BODY_LIMIT = 1000


class StreamsMobilePush(models.Model):
    """Очередь исходящих пушей (§4 design-phase6).

    Запись создаётся синхронно в точках рассылки streams, отправка идёт
    асинхронно через queue_job (`_streams_process`), cron — страховка от
    выключенного jobrunner. Пока ключей FCM нет, транспорт — заглушка:
    записи получают state='skipped'.
    """
    _name = 'streams.mobile.push'
    _description = 'Streams Mobile Push'
    _order = 'id desc'

    device_id = fields.Many2one(
        'streams.mobile.device', required=True, index=True,
        ondelete='cascade')
    title = fields.Char()
    body = fields.Char()
    data = fields.Char(help="JSON payload for deep linking.")
    state = fields.Selection(
        [
            ('queued', 'Queued'),
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
        ], default='queued', required=True, index=True)
    error = fields.Char()

    # ------------------------------------------------------------
    # ПОСТАНОВКА
    # ------------------------------------------------------------

    @api.model
    def _streams_enqueue(self, partners, title, body, data=None):
        """Поставить пуш всем активным устройствам партнёров.

        ACL решается ДО вызова (политика по потокам и права на запись —
        зона ответственности вызывающего); здесь только доставка.
        """
        if not partners:
            return self.browse()
        devices = self.env['streams.mobile.device'].sudo().search([
            ('user_id.partner_id', 'in', partners.ids),
            ('push_enabled', '=', True),
        ])
        if not devices:
            return self.browse()
        payload = json.dumps(data or {})
        pushes = self.sudo().create([
            {
                'device_id': device.id,
                'title': (title or '')[:240],
                'body': (body or '')[:PUSH_BODY_LIMIT],
                'data': payload,
            }
            for device in devices
        ])
        pushes.with_delay(
            priority=15,
            description='streams_mobile: push delivery',
        )._streams_process()
        return pushes

    # ------------------------------------------------------------
    # ОТПРАВКА
    # ------------------------------------------------------------

    def _streams_process(self):
        """Отправить очередь; вызывается job'ом и cron-страховкой."""
        for push in self.sudo().filtered(lambda p: p.state == 'queued'):
            push._streams_send_one()

    def _streams_send_one(self):
        self.ensure_one()
        device = self.device_id
        if not device.active or not device.push_enabled:
            self.write({'state': 'skipped', 'error': 'device inactive'})
            return
        if not device.sudo().push_token:
            self.write({'state': 'skipped', 'error': 'no push token'})
            return
        if not self._streams_fcm_configured():
            # транспорт-заглушка до появления ключей Firebase
            _logger.debug(
                'streams_mobile: FCM не настроен, пуш %s пропущен', self.id)
            self.write({'state': 'skipped', 'error': 'fcm not configured'})
            return
        try:
            self._streams_fcm_send()
            self.write({'state': 'sent', 'error': False})
        except Exception as error:  # транспортная ошибка не роняет пачку
            _logger.warning(
                'streams_mobile: пуш %s не отправлен: %s', self.id, error)
            self.write({'state': 'failed', 'error': str(error)[:500]})

    @api.model
    def _streams_fcm_configured(self):
        return bool(self.env['ir.config_parameter'].sudo().get_param(
            'streams_mobile.fcm_service_account_json'))

    def _streams_fcm_send(self):
        """FCM HTTP v1. Реализуется при появлении ключей (см. roadmap)."""
        raise NotImplementedError('FCM transport is not configured')

    @api.model
    def _streams_cron_process(self):
        """Страховка: доотправить зависшие queued (jobrunner мог быть выключен)."""
        pending = self.sudo().search([('state', '=', 'queued')], limit=200)
        if pending:
            pending._streams_process()

    @api.autovacuum
    def _gc_old_pushes(self):
        self.sudo().search([
            ('create_date', '<', fields.Datetime.subtract(
                fields.Datetime.now(), days=30)),
        ]).unlink()
