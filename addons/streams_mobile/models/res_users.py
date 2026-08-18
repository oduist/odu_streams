# -*- encoding: utf-8 -*-
from odoo import models


class ResUsers(models.Model):
    """Смена пароля инвалидирует мобильные токены (§2 design-phase6)."""
    _inherit = 'res.users'

    def write(self, vals):
        result = super().write(vals)
        if 'password' in vals and self.ids:
            self.env['streams.mobile.device']._streams_revoke_for_users(self)
        return result
