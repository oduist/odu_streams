# -*- encoding: utf-8 -*-
from odoo import models, fields


class ResUsersSettings(models.Model):
    """Состояние категории «Messages» в сайдбаре Discuss (§11.3).

    Ядро отдаёт все неавтоматические поля этой модели в `init_messaging`
    (`_res_users_settings_format`), поэтому клиенту достаточно объявить
    поле здесь — отдельная выдача не нужна.
    """
    _inherit = 'res.users.settings'

    is_discuss_sidebar_category_streams_open = fields.Boolean(
        string="Is discuss sidebar category messages open?", default=True)
    # Персональный тумблер звука уведомлений (§12.4). Попапы и счётчики от
    # него не зависят — глушится только звук.
    is_streams_notify_sound_muted = fields.Boolean(
        string="Is the notification sound muted?", default=False)
