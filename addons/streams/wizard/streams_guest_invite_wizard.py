# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StreamsGuestInviteWizard(models.TransientModel):
    """Приглашение клиента в канал записи (§9.2, А6, Б1).

    Открывается и из шапки канала Discuss, и из чаттера записи (решение 2
    от 2026-08-18). Во втором случае канала может ещё не быть — тогда
    приглашение его создаёт: это пятый триггер §5.1.
    """
    _name = 'streams.guest.invite.wizard'
    _description = 'Invite a Customer to the Chat'

    channel_id = fields.Many2one(
        'discuss.channel', string='Channel', readonly=True)
    res_model = fields.Char(string='Related Document Model', required=True)
    res_id = fields.Integer(string='Related Document ID', required=True)
    record_name = fields.Char(string='Record', readonly=True)
    partner_ids = fields.Many2many(
        'res.partner', 'streams_guest_invite_wizard_partner_rel',
        'wizard_id', 'partner_id', string='Contacts',
        # в 19 у res.partner.type значения 'private' больше нет — лист убран
        domain="[('is_company', '=', False)]",
        help="Each contact receives their own personal link.")
    history_from = fields.Datetime(
        string='Show History From', required=True,
        default=fields.Datetime.now)
    send_email = fields.Boolean(
        string='Send the invitation by email', default=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')],
        string='State', default='draft', required=True)
    link_ids = fields.One2many(
        'streams.guest.invite.wizard.line', 'wizard_id',
        string='Personal links')
    access_ids = fields.One2many(
        'streams.guest.invite.wizard.line', 'access_wizard_id',
        string='Existing access')
    reply_warning = fields.Char(string='Reply Warning', readonly=True)

    # ------------------------------------------------------------
    # ОТКРЫТИЕ ДИАЛОГА
    # ------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        """Модель и запись приходят контекстом действия.

        Канал здесь не создаётся: открыть и закрыть диалог не должно
        оставлять после себя канал. Создание — в `action_invite`.
        """
        values = super().default_get(fields_list)
        channel = self.env['discuss.channel'].browse(
            self.env.context.get('default_channel_id') or []).exists()
        res_model = self.env.context.get('default_res_model')
        res_id = self.env.context.get('default_res_id')
        if channel:
            res_model = channel.res_model
            res_id = channel.res_id
        if not res_model or not res_id:
            return values
        record = self._streams_check_record(res_model, res_id)
        if not channel:
            channel = record._streams_find_channel()
        values.update({
            'channel_id': channel.id if channel else False,
            'res_model': res_model,
            'res_id': res_id,
            'record_name': record.display_name,
        })
        if channel:
            values['access_ids'] = [
                (0, 0, line)
                for line in self._streams_access_lines(channel)
            ]
        return values

    @api.model
    def _streams_check_record(self, res_model, res_id):
        """Приглашать в обсуждение записи вправе тот, кто её читает."""
        if res_model not in self.env:
            raise UserError(_("Unknown model: %s") % res_model)
        record = self.env[res_model].browse(res_id).exists()
        if not record:
            raise UserError(_("The record no longer exists."))
        record.check_access('read')
        return record

    @api.model
    def _streams_access_lines(self, channel):
        """Уже выданные доступы канала — значениями, а не ссылками.

        Модель участника закрыта на `base.group_system` (Р15), поэтому
        обычный пользователь читает её через визард, а не напрямую.
        """
        participants = self.env[
            'mail.channel.external.participant'].sudo().search([
                ('channel_id', '=', channel.id)])
        return [
            {
                'partner_id': participant.partner_id.id,
                'participant_id': participant.id,
                'invited_on': participant.create_date,
                'last_seen': participant.last_seen,
                'is_link_consumed': participant.is_link_consumed,
            }
            for participant in participants
        ]

    # ------------------------------------------------------------
    # ПРИГЛАШЕНИЕ
    # ------------------------------------------------------------

    def action_invite(self):
        """Выдать каждому контакту свою ссылку (§9.2)."""
        self.ensure_one()
        if not self.partner_ids:
            raise UserError(_("Select at least one contact to invite."))
        record = self._streams_check_record(self.res_model, self.res_id)
        channel = self.channel_id
        if not channel:
            # приглашение из чаттера создаёт канал (§5.1, пятый триггер)
            channel = record._streams_get_or_create_channel()
            self.channel_id = channel.id
        participant_model = self.env['mail.channel.external.participant']
        lines = []
        warning = False
        for partner in self.partner_ids:
            participant = participant_model._streams_get_or_create(
                channel, partner, history_from=self.history_from)
            link_url = participant._streams_issue_link()
            participant._streams_get_or_create_anchor()
            email_sent = False
            if self.send_email and partner.email:
                mail = participant._streams_send_template(
                    'streams.mail_template_guest_invite', link_url,
                    force_send=True)
                email_sent = bool(mail)
            if not participant._streams_reply_to():
                warning = _(
                    "Replies by email cannot be routed: the catchall alias and "
                    "domain are not configured.")
            lines.append((0, 0, {
                'partner_id': partner.id,
                'participant_id': participant.id,
                'url': link_url,
                'email_sent': email_sent,
                'invited_on': participant.create_date,
                'last_seen': participant.last_seen,
                'is_link_consumed': participant.is_link_consumed,
            }))
            _logger.info(
                'streams: гостевой доступ выдан контакту %s к каналу %s',
                partner.id, channel.id)
        self.write({
            'state': 'done',
            'link_ids': lines,
            'reply_warning': warning,
            'access_ids': [(5, 0, 0)] + [
                (0, 0, line) for line in self._streams_access_lines(channel)
            ],
        })
        return self._streams_reopen()

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}

    def _streams_reopen(self):
        """Показать тот же визард со ссылками (§9.2)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Invite a customer to this chat"),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }


class StreamsGuestInviteWizardLine(models.TransientModel):
    """Строка диалога: выданная ссылка либо уже существующий доступ.

    Значения копируются из участника, а не читаются связью: модель
    участника закрыта на `base.group_system` (Р15), а диалогом
    пользуется обычный сотрудник.
    """
    _name = 'streams.guest.invite.wizard.line'
    _description = 'Guest Invitation Line'

    wizard_id = fields.Many2one(
        'streams.guest.invite.wizard', string='Wizard', ondelete='cascade')
    access_wizard_id = fields.Many2one(
        'streams.guest.invite.wizard', string='Access Wizard',
        ondelete='cascade')
    partner_id = fields.Many2one(
        'res.partner', string='Contact', readonly=True)
    participant_id = fields.Integer(string='Participant', readonly=True)
    url = fields.Char(string='Personal link (works once)', readonly=True)
    email_sent = fields.Boolean(string='Email sent', readonly=True)
    invited_on = fields.Datetime(string='Invited On', readonly=True)
    last_seen = fields.Datetime(string='Last Seen', readonly=True)
    is_link_consumed = fields.Boolean(string='Link Used', readonly=True)

    def action_revoke_participant(self):
        """Отозвать доступ (§9.3): после этого гость не видит ничего."""
        self.ensure_one()
        if not self.participant_id:
            return True
        participant = self.env[
            'mail.channel.external.participant'].sudo().browse(
                self.participant_id).exists()
        if participant:
            participant._streams_revoke()
        wizard = self.access_wizard_id or self.wizard_id
        if wizard:
            wizard.write({
                'access_ids': [(5, 0, 0)] + [
                    (0, 0, line)
                    for line in wizard._streams_access_lines(wizard.channel_id)
                ],
            })
            return wizard._streams_reopen()
        return True
