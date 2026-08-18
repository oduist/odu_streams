# -*- encoding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.osv import expression

from odoo.addons.mail.controllers.discuss import DiscussController


class DiscussController(DiscussController):

    # пустой @http.route() обязателен: без него метод теряет routing
    # родителя и маршрут просто исчезает из карты (404)
    @http.route()
    def mail_channel_messages(self, channel_id, max_id=None, min_id=None,
                              limit=30, **kwargs):
        """Лента канала = собственные сообщения плюс проекции записи.

        Домен ядра зашит прямо в контроллере, а не в
        `_channel_fetch_message`, поэтому переопределять приходится здесь.
        """
        channel_partner_sudo = request.env[
            'mail.channel.partner']._get_as_sudo_from_request_or_raise(
                request=request, channel_id=int(channel_id))
        channel = channel_partner_sudo.channel_id
        domain = expression.AND([
            channel._streams_message_domain(),
            [('message_type', '!=', 'user_notification')],
        ])
        return channel_partner_sudo.env['mail.message']._message_fetch(
            domain=domain, max_id=max_id, min_id=min_id, limit=limit)
