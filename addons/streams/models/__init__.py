# -*- encoding: utf-8 -*-
from . import mail_field_subscription
from . import mail_notify
from . import mail_message
from . import discuss_channel
from . import discuss_channel_member
from . import mail_channel_external_participant
from . import mail_thread
from . import mail_activity
# mail_compose_message: в 19 ядровый default_get сам принимает
# `default_subtype_xmlid` — наш override стал не нужен и удалён
# mail_wizard_invite: модели mail.wizard.invite в 19 нет (заменена на
# mail.followers.edit); серверный фильтр внутренних пользователей живёт
# в mail_thread.message_subscribe, через который идёт и новый визард
from . import res_users
from . import res_users_settings
from . import res_config_settings
