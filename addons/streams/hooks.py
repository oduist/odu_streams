# -*- encoding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Внутренние пользователи не получают писем — переводим их на inbox.

    Поле `notification_type` уже существует к моменту установки, поэтому
    достаточно однократного массового перевода; новые и изменённые
    пользователи удерживаются на inbox override'ом res.users.
    """
    users = env['res.users'].with_context(active_test=False).search([
        ('share', '=', False),
        ('notification_type', '!=', 'inbox'),
    ])
    if users:
        users.write({'notification_type': 'inbox'})
        _logger.info(
            'streams: %s внутренних пользователей переведены на inbox',
            len(users))
