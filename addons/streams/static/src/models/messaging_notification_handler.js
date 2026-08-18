/** @odoo-module **/

import { registerInstancePatchModel } from '@mail/model/model_core';

const PATCH_ID = 'streams/static/src/models/messaging_notification_handler.js';

registerInstancePatchModel('mail.messaging_notification_handler', PATCH_ID, {
    /**
     * Изменения приезжают своим типом уведомления, а не
     * `mail.channel/new_message`: тело change-сообщения по шине не идёт
     * (§8.4 — доступ к записи мог пропасть), клиенту сообщается только
     * факт «лента канала обновилась».
     *
     * @override
     */
    _handleNotification(message) {
        if (message.type === 'streams.changes/updated') {
            this.messaging.messagingBus.trigger(
                'streams-changes-updated', message.payload);
            return;
        }
        return this._super(message);
    },
});
