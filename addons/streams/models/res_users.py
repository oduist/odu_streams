# -*- encoding: utf-8 -*-
import logging

from odoo import models, api

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """Внутренние пользователи работают только в Odoo (§7).

    Системные письма Odoo — сброс пароля, приглашение пользователя — идут
    мимо `_notify_thread` и этой настройкой не затрагиваются.
    """
    _inherit = 'res.users'

    # Дефолт поля notification_type НЕ переопределяется: в 19 на res_users
    # есть CHECK-констрейнт «share-пользователь не может быть inbox», и
    # общий дефолт inbox ронял бы создание портальных пользователей ещё до
    # нашей пост-обработки. Внутренних на inbox переводит
    # _streams_force_inbox после create/write.

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._streams_force_inbox()
        return users

    def write(self, vals):
        result = super().write(vals)
        if {'notification_type', 'group_ids', 'active'} & set(vals):
            self._streams_force_inbox()
        return result

    def _init_messaging(self, store):
        """Уведомления едут одним payload'ом со стартом клиента (§12.4).

        Счётчик бейджа, id личного канала и накопившиеся, но ещё не
        показанные попапы — всё это нужно клиенту сразу, отдельный RPC
        только добавил бы round-trip. В 19 метод ничего не возвращает,
        а наполняет переданный Store.
        """
        super()._init_messaging(store)
        # payload считается для владельца сессии, а не для того, кто вызвал:
        # ядро зовёт метод на `request.env.user`, но подстраховаться дешевле
        store.add_global_values(
            streams_notify=self.env['mail.notify'].with_user(
                self)._streams_init_messaging())

    def _streams_force_inbox(self):
        """Удержать внутренних на inbox, а внешних (share) — на email.

        Пишем через super(), чтобы не уйти в рекурсию собственного write.
        """
        internal = self.sudo().filtered(
            lambda user: not user.share and user.notification_type != 'inbox')
        if internal:
            super(ResUsers, internal).write({'notification_type': 'inbox'})
            _logger.debug(
                'streams: notification_type=inbox выставлен пользователям %s',
                internal.ids)
        external = self.sudo().filtered(
            lambda user: user.share and user.notification_type != 'email')
        if external:
            super(ResUsers, external).write({'notification_type': 'email'})
            _logger.debug(
                'streams: notification_type=email возвращён share-пользователям %s',
                external.ids)
