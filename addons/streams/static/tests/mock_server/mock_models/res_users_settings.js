import { mailModels } from "@mail/../tests/mail_test_helpers";

import { fields } from "@web/../tests/web_test_helpers";

/**
 * Настройки пользователя, которые добавляет streams (§11.3, §12.4).
 *
 * Поля описаны на сервере (`models/res_users_settings.py`) и приезжают в
 * mock-схему сами, а вот дефолты — нет: `fields_get` их не отдаёт. Для
 * `is_discuss_sidebar_category_streams_open` это важно, иначе категория
 * «Messages» в сайдбаре считается свёрнутой и её каналы не рисуются.
 */
export class ResUsersSettings extends mailModels.ResUsersSettings {
    is_discuss_sidebar_category_streams_open = fields.Generic({ default: true });
    is_streams_notify_sound_muted = fields.Generic({ default: false });
    streams_partner_scope = fields.Generic({ default: "related" });
}
