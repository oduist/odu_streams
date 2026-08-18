# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StreamsFieldSubscriptionWizard(models.TransientModel):
    """Диалог кнопки Changes в чаттере записи (§8.1, §11.1).

    Визард, а не OWL-диалог: подписка — это выбор из m2m, а форма
    TransientModel даёт его бесплатно, вместе с поиском по полям.
    """
    _name = 'streams.field.subscription.wizard'
    _description = 'Subscribe to Record Field Changes'

    res_model = fields.Char(string='Related Document Model', required=True)
    res_id = fields.Integer(string='Related Document ID', required=True)
    record_name = fields.Char(string='Record', readonly=True)
    available_field_ids = fields.Many2many(
        'ir.model.fields', 'streams_subscription_wizard_available_rel',
        'wizard_id', 'field_id', string='Available Fields')
    field_ids = fields.Many2many(
        'ir.model.fields', 'streams_subscription_wizard_selected_rel',
        'wizard_id', 'field_id', string='Tracked Fields',
        help="Changes of these fields land in your personal Changes stream.")

    @api.model
    def default_get(self, fields_list):
        """Предзаполнение состоянием подписки (§8.1).

        Диалог открывается из чаттера, поэтому модель и запись приходят
        контекстом действия; сам список полей и отметки считает сервер —
        клиенту решать, что пользователю доступно, нельзя.
        """
        values = super().default_get(fields_list)
        res_model = self.env.context.get('default_res_model')
        res_id = self.env.context.get('default_res_id')
        if not res_model or not res_id:
            return values
        if res_model not in self.env:
            raise UserError(_("Unknown model: %s") % res_model)
        record = self.env[res_model].browse(res_id).exists()
        if not record:
            raise UserError(_("The record no longer exists."))
        state = record.streams_get_field_subscription()
        values.update({
            'res_model': res_model,
            'res_id': res_id,
            'record_name': record.display_name,
            'available_field_ids': [
                (6, 0, [item['id'] for item in state['available_fields']])],
            'field_ids': [(6, 0, state['field_ids'])],
        })
        return values

    def action_save(self):
        """Сохранить выбор пользователя и закрыть диалог."""
        self.ensure_one()
        if self.res_model not in self.env:
            raise UserError(_("Unknown model: %s") % self.res_model)
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_("The record no longer exists."))
        record.streams_set_field_subscription(self.field_ids.ids)
        return {'type': 'ir.actions.act_window_close'}

    def action_unsubscribe(self):
        """Снять подписку целиком: пустой выбор ≡ отписка."""
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id).exists()
        if record:
            record.streams_set_field_subscription([])
        return {'type': 'ir.actions.act_window_close'}
