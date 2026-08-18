# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class MailWizardInvite(models.TransientModel):
    """Приглашать в followers можно только внутренних пользователей (§10.3).

    Домен во вьюхе (`veles_invite_followers`) — подсказка интерфейса;
    серверная фильтрация в `add_followers` обязательна, потому что визард
    вызывается и напрямую.

    Письмо приглашения внутреннему сотруднику не уходит: `add_followers`
    зовёт `_notify_record_by_email` напрямую, а наш override отбрасывает
    получателей с `type == 'user'`.
    """
    _inherit = 'mail.wizard.invite'

    partner_ids = fields.Many2many(
        domain=[('type', '!=', 'private'), ('user_ids.share', '=', False)])

    def add_followers(self):
        for wizard in self:
            allowed = wizard.partner_ids.filtered(
                lambda partner: partner.with_context(
                    active_test=False).user_ids.filtered(
                        lambda user: not user.share))
            if allowed != wizard.partner_ids:
                _logger.debug(
                    'streams: из приглашения убраны партнёры без внутреннего '
                    'пользователя: %s', (wizard.partner_ids - allowed).ids)
                wizard.partner_ids = allowed
        return super().add_followers()
