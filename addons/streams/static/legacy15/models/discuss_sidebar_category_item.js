/** @odoo-module **/

import { registerInstancePatchModel } from '@mail/model/model_core';

const PATCH_ID = 'streams/static/src/models/discuss_sidebar_category_item.js';

// Виды каналов, у которых счётчик берётся из message_unread_counter, а не
// из needaction: в канале записи (§5.7) и в личном Changes (§8.3) его
// считает сервер по своим правилам.
const STREAMS_COUNTED_KINDS = ['record', 'changes'];

registerInstancePatchModel('mail.discuss_sidebar_category_item', PATCH_ID, {
    /**
     * У канала записи считается непрочитанное, а не needaction: ядровый
     * switch по `channel_type` для типа 'channel' берёт needaction, а
     * серверный счётчик потоков (§5.7) живёт в message_unread_counter.
     *
     * @override
     */
    _computeCategoryCounterContribution() {
        if (this.channel && STREAMS_COUNTED_KINDS.includes(
                this.channel.streamsChannelKind)) {
            return this.channel.localMessageUnreadCounter > 0 ? 1 : 0;
        }
        return this._super();
    },
    /**
     * @override
     */
    _computeCounter() {
        if (this.channel && STREAMS_COUNTED_KINDS.includes(
                this.channel.streamsChannelKind)) {
            return this.channel.localMessageUnreadCounter;
        }
        return this._super();
    },
});
