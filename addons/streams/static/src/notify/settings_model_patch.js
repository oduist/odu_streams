import { Settings } from "@mail/core/common/settings_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

/**
 * Персональный Mute звука уведомлений (E9) на клиенте.
 *
 * Значение доезжает само: ядро 19 сериализует `res.users.settings`
 * целиком (`_res_users_settings_format` без списка полей), и на старте,
 * и bus-пушем `res.users.settings` после `set_res_users_settings`.
 * Объявление здесь нужно не для доставки, а для реактивности: owl не
 * отслеживает ключ, которого в объекте ещё нет, поэтому тумблер в шапке
 * ленты не перерисовался бы до первой записи настройки.
 */
patch(Settings.prototype, {
    setup() {
        super.setup(...arguments);
        /** @type {boolean} */
        this.is_streams_notify_sound_muted = fields.Attr(false);
    },
});
