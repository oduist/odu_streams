/** @odoo-module **/

import {
    registerClassPatchModel,
    registerFieldPatchModel,
    registerInstancePatchModel,
} from '@mail/model/model_core';
import { attr } from '@mail/model/model_field';

import { STREAMS_FILTER_DEFAULTS } from '@streams/js/streams_filters';

const PATCH_ID = 'streams/static/src/models/thread.js';

registerFieldPatchModel('mail.thread', PATCH_ID, {
    /**
     * Вид канала: 'record' для канала записи, иначе undefined.
     */
    streamsChannelKind: attr(),
    /**
     * Фильтры отображения потоков, персистентные per-channel per-user.
     */
    streamsFilters: attr({
        default: STREAMS_FILTER_DEFAULTS,
    }),
    streamsResId: attr(),
    streamsResModel: attr(),
});

registerClassPatchModel('mail.thread', PATCH_ID, {
    /**
     * @override
     */
    convertData(data) {
        const data2 = this._super(data);
        if ('channel_kind' in data) {
            data2.streamsChannelKind = data.channel_kind || undefined;
        }
        if ('res_model' in data) {
            data2.streamsResModel = data.res_model || undefined;
        }
        if ('res_id' in data) {
            data2.streamsResId = data.res_id || undefined;
        }
        if ('streams_filters' in data) {
            data2.streamsFilters = Object.assign(
                {}, STREAMS_FILTER_DEFAULTS, data.streams_filters);
        }
        return data2;
    },
});

registerInstancePatchModel('mail.thread', PATCH_ID, {
    /**
     * Каналы записей живут в собственной категории сайдбара (§11.3).
     * `channel_type` при этом остаётся 'channel': все ядровые computed
     * категории — switch по типу канала и на незнакомом типе молча дают
     * undefined.
     *
     * @override
     */
    _getDiscussSidebarCategory() {
        if (this.streamsChannelKind === 'record') {
            return this.messaging.discuss.categoryStreams;
        }
        // личные Changes и Notifications живут в ядровой категории
        // Channels (решение пользователя 2026-08-18)
        return this._super();
    },
});
