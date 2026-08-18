# -*- encoding: utf-8 -*-
from odoo import models, api


class MailComposeMessage(models.TransientModel):
    """Полный композер умеет принимать подтип по xmlid (§11.1).

    Кнопка Send Message чаттера открывает ядровой полный композер и должна
    задать ему подтип `streams.mt_message`. Через `default_subtype_id`
    клиенту пришлось бы знать id записи, поэтому принимаем xmlid.
    """
    _inherit = 'mail.compose.message'

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        xmlid = self.env.context.get('default_subtype_xmlid')
        if xmlid and 'subtype_id' in fields_list:
            # ядровое поле само дефолтится в mail.mt_comment, поэтому
            # затираем безусловно: явный контекст сильнее дефолта
            subtype_id = self.env['ir.model.data']._xmlid_to_res_id(
                xmlid, raise_if_not_found=False)
            if subtype_id:
                values['subtype_id'] = subtype_id
        return values
