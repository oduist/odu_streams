import { Settings } from "@mail/core/common/settings_model";
import { fields } from "@mail/core/common/record";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

/**
 * Дефолт охвата чаттера контакта — дубль серверного
 * (`models/res_users_settings.py`, `streams_partner_scope`).
 *
 * Нужен именно как дубль: сегмент-кнопки надо уметь нарисовать до того,
 * как приедет `res.users.settings` (а у пользователя без записи настроек
 * её не будет вовсе — сервер в этом случае тоже читает `related`).
 */
export const STREAMS_PARTNER_SCOPE_DEFAULT = "related";

/**
 * Охваты в порядке сегмента (§18.2).
 *
 * Тултипы описывают ровно то, что добавляет каждый уровень: подписи из
 * одного слова сами по себе не объясняют, чем Related отличается от
 * Company.
 */
export const STREAMS_PARTNER_SCOPES = [
    {
        scope: "direct",
        label: _t("Direct"),
        title: _t("Show only this contact's own messages"),
    },
    {
        scope: "related",
        label: _t("Related"),
        title: _t("Add messages of the records where this contact is the customer"),
    },
    {
        scope: "company",
        label: _t("Company"),
        title: _t("Add messages of every contact of this organization"),
    },
];

/**
 * Персональный охват чаттера контакта (§18.2) на клиенте.
 *
 * Значение доезжает само: ядро 19 сериализует `res.users.settings`
 * целиком (`_res_users_settings_format` без списка полей), и на старте,
 * и bus-пушем `res.users.settings` после `set_res_users_settings`.
 * Объявление здесь нужно не для доставки, а для реактивности: owl не
 * отслеживает ключ, которого в объекте ещё нет, поэтому сегмент-кнопки
 * не перерисовались бы до первой записи настройки.
 */
patch(Settings.prototype, {
    setup() {
        super.setup(...arguments);
        /** @type {"direct"|"related"|"company"} */
        this.streams_partner_scope = fields.Attr(STREAMS_PARTNER_SCOPE_DEFAULT);
    },
});
