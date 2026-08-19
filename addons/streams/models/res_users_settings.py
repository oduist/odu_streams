# -*- encoding: utf-8 -*-
from odoo import models, fields


class ResUsersSettings(models.Model):
    """Состояние категории «Messages» в сайдбаре Discuss (§11.3).

    В 19 модель живёт в base, но сериализация не поменялась: ядро отдаёт
    все неавтоматические поля целиком через `_res_users_settings_format`
    (web кладёт их в session_info, mail — в Store при `_init_store_data`,
    точечные правки едут через `set_res_users_settings`). Поэтому клиенту
    достаточно объявить поле здесь — отдельная выдача не нужна.
    """
    _inherit = 'res.users.settings'

    is_discuss_sidebar_category_streams_open = fields.Boolean(
        string="Is discuss sidebar category messages open?", default=True)
    # Персональный тумблер звука уведомлений (§12.4). Попапы и счётчики от
    # него не зависят — глушится только звук.
    is_streams_notify_sound_muted = fields.Boolean(
        string="Is the notification sound muted?", default=False)
    # Охват чаттера контакта (§18.2). Персональный и персистентный;
    # клиент его в запросе ленты НЕ передаёт — сервер читает настройку
    # сам, иначе тот же охват пришлось бы дублировать в каждом
    # потребителе `_message_fetch`.
    streams_partner_scope = fields.Selection(
        [('direct', 'Direct'), ('related', 'Related'), ('company', 'Company')],
        string='Partner Chatter Scope', default='related')
