# -*- encoding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import models, fields, api, _, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# `_action_done` сам вызывает unlink, и без этого флага закрытие активности
# порождало бы ещё и «отменена».
_DONE_CONTEXT = 'streams_activity_done'


class MailActivity(models.Model):
    """Синтетические сообщения о событиях активности (§13).

    Сообщения уходят подтипом `streams.mt_activity`: он internal и
    `default=False`, поэтому подписчиков у него нет и уведомлений
    активности не порождают.
    """
    _inherit = 'mail.activity'

    @api.model_create_multi
    def create(self, vals_list):
        activities = super().create(vals_list)
        for activity in activities:
            activity._streams_log_event('scheduled')
        return activities

    def write(self, values):
        previous = {
            activity.id: (activity.date_deadline, activity.user_id)
            for activity in self
        } if ('date_deadline' in values or 'user_id' in values) else {}
        result = super().write(values)
        for activity in self:
            old_deadline, old_user = previous.get(
                activity.id, (None, None))
            if old_deadline and activity.date_deadline != old_deadline:
                activity._streams_log_event('rescheduled')
            if old_user is not None and activity.user_id != old_user:
                activity._streams_log_event('reassigned')
        return result

    def unlink(self):
        if not self.env.context.get(_DONE_CONTEXT):
            for activity in self:
                activity._streams_log_event('cancelled')
        return super().unlink()

    def _action_done(self, feedback=False, attachment_ids=None):
        """Закрытие активности.

        Своё сообщение не пишем: ядро постит богатое сообщение по шаблону
        `mail.message_activity_done` (тип активности, feedback, перенос
        вложений) с подтипом `mail.mt_activities`. Чтобы не плодить дубль,
        переподтипляем ядровое сообщение в Activity и уже с правильным
        подтипом проводим его через канал записи.
        """
        messages, next_activities = super(
            MailActivity,
            self.with_context(**{_DONE_CONTEXT: True}),
        )._action_done(feedback=feedback, attachment_ids=attachment_ids)
        subtype_id = self.env['ir.model.data']._xmlid_to_res_id(
            'streams.mt_activity', raise_if_not_found=False)
        if subtype_id:
            for message in messages.sudo():
                if not message.model or not message.res_id:
                    continue
                message.write({'subtype_id': subtype_id})
                record = self.env[message.model].browse(message.res_id)
                if record.exists() and hasattr(
                        record, '_streams_handle_posted_message'):
                    record._streams_handle_posted_message(message)
        return messages, next_activities

    # ------------------------------------------------------------
    # ВНУТРЕННЕЕ
    # ------------------------------------------------------------

    def _streams_activity_author(self):
        """Актор события; для кронов и серверных действий — OdooBot."""
        if self.env.uid == SUPERUSER_ID:
            return self.env.ref('base.partner_root', raise_if_not_found=False)
        return self.env.user.partner_id

    def _streams_event_body(self, event, feedback=False):
        self.ensure_one()
        name = self.summary or self.activity_type_id.name or _('Activity')
        deadline = fields.Date.to_string(self.date_deadline) or ''
        assignee = self.user_id.display_name or ''
        if event == 'scheduled':
            text = _(
                'Activity scheduled: %(activity)s — due %(deadline)s, '
                'assigned to %(assignee)s',
                activity=name, deadline=deadline, assignee=assignee)
        elif event == 'rescheduled':
            text = _(
                'Activity rescheduled: %(activity)s — new deadline '
                '%(deadline)s',
                activity=name, deadline=deadline)
        elif event == 'reassigned':
            text = _(
                'Activity reassigned: %(activity)s — now assigned to '
                '%(assignee)s',
                activity=name, assignee=assignee)
        elif event == 'cancelled':
            text = _('Activity cancelled: %(activity)s', activity=name)
        else:
            text = _('Activity done: %(activity)s', activity=name)
        body = Markup('<p>%s</p>') % escape(text)
        if feedback:
            body += Markup('<p><strong>%s</strong><br/>%s</p>') % (
                escape(_('Feedback')),
                escape(feedback).replace('\n', Markup('<br/>')))
        return body

    def _streams_log_event(self, event, feedback=False):
        """Записать событие активности в чаттер записи-источника."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return
        if self.res_model not in self.env:
            return
        record = self.env[self.res_model].sudo().browse(self.res_id).exists()
        if not record or not hasattr(record, 'message_post'):
            return
        if not record._streams_channel_enabled():
            return
        author = self._streams_activity_author()
        try:
            record.message_post(
                body=self._streams_event_body(event, feedback=feedback),
                subtype_xmlid='streams.mt_activity',
                message_type='notification',
                author_id=author.id if author else False,
            )
        except Exception:
            # событие активности не должно ронять бизнес-операцию
            _logger.exception(
                'streams: не удалось записать событие "%s" активности %s',
                event, self.id)
