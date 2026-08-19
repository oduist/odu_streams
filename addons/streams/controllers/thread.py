# -*- encoding: utf-8 -*-
"""Сужение `set_message_done` для чаттера контакта (§18.6, Р8).

Ядровый `/mail/thread/messages` гасит needaction по ВСЕМ отданным
сообщениям (`mail/controllers/thread.py:65-66`). Для агрегированной
ленты контакта это означало бы, что открытие карточки клиента гасит
уведомления по чужим записям — лиду, заказу, счёту, — что прямо
запрещено §18.4 и §18.6.

Ловушка сидит в роуте, а не в `_message_fetch`, поэтому наша врезка в
выборку её не видит: это единственная причина, по которой роут
переопределяется. Сама выборка остаётся ядровой.
"""
from odoo import http
from odoo.http import request
from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.tools.discuss import Store


class StreamsThreadController(ThreadController):

    @http.route()
    def mail_thread_messages(self, thread_model, thread_id, fetch_params=None):
        if thread_model != 'res.partner':
            return super().mail_thread_messages(
                thread_model, thread_id, fetch_params=fetch_params)
        thread = self._get_thread_with_access(
            thread_model, thread_id, mode='read')
        res = request.env['mail.message']._message_fetch(
            domain=None, thread=thread, **(fetch_params or {}))
        messages = res.pop('messages')
        if not request.env.user._is_public():
            # гасим только сообщения самой карточки: виртуальные приехали
            # с чужих записей и их needaction нас не касается
            messages.filtered(
                lambda message: message.model == 'res.partner'
                and message.res_id == thread.id).set_message_done()
        return {
            **res,
            'data': Store().add(messages).get_result(),
            'messages': messages.ids,
        }
