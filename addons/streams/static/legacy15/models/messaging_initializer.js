/** @odoo-module **/

import { registerInstancePatchModel } from '@mail/model/model_core';
import { insertAndReplace } from '@mail/model/model_field_command';

import { withStreamsNotifyService } from '@streams/js/notify_bridge';

const PATCH_ID = 'streams/static/src/models/messaging_initializer.js';

registerInstancePatchModel('mail.messaging_initializer', PATCH_ID, {
    /**
     * Уведомления приезжают вместе со стартом клиента (§12.4): счётчик
     * бейджа, id личного канала и накопившиеся попапы. Отдельный RPC ради
     * этого не нужен — payload и так вычитывается целиком.
     *
     * @override
     * @param {Object} data
     */
    async _init(data) {
        const result = await this._super(...arguments);
        if (data && data.streams_notify) {
            withStreamsNotifyService(
                service => service.init(data.streams_notify));
        }
        return result;
    },
    /**
     * @override
     * @param {Object} resUsersSettings
     * @param {boolean} resUsersSettings.is_discuss_sidebar_category_streams_open
     */
    _initResUsersSettings(resUsersSettings) {
        const {
            is_discuss_sidebar_category_streams_open,
        } = resUsersSettings;
        this.messaging.discuss.update({
            categoryStreams: insertAndReplace({
                isServerOpen: is_discuss_sidebar_category_streams_open,
                name: this.env._t("Messages"),
                serverStateKey: 'is_discuss_sidebar_category_streams_open',
                sortComputeMethod: 'last_action',
                supportedChannelTypes: ['channel'],
            }),
        });
        // персональный Mute звука уведомлений (§12.4)
        withStreamsNotifyService(service => service.initSettings({
            id: resUsersSettings.id,
            is_streams_notify_sound_muted:
                resUsersSettings.is_streams_notify_sound_muted,
        }));
        this._super(...arguments);
    },
});
