/** @odoo-module **/

import {
    registerFieldPatchModel,
    registerIdentifyingFieldsPatch,
    registerInstancePatchModel,
} from '@mail/model/model_core';
import { one2one } from '@mail/model/model_field';
import { clear } from '@mail/model/model_field_command';

const PATCH_ID = 'streams/static/src/models/discuss_sidebar_category.js';

registerFieldPatchModel('mail.discuss_sidebar_category', PATCH_ID, {
    discussAsStreams: one2one('mail.discuss', {
        inverse: 'categoryStreams',
        readonly: true,
    }),
});

registerIdentifyingFieldsPatch(
    'mail.discuss_sidebar_category', PATCH_ID, identifyingFields => {
        identifyingFields[0].push('discussAsStreams');
    });

registerInstancePatchModel('mail.discuss_sidebar_category', PATCH_ID, {
    /**
     * Канал записи остаётся `channel_type='channel'`, поэтому ядровая
     * категория Channels тоже считает его своим и, открытая, перетягивает
     * элемент сайдбара к себе (`categoryItems.channel` — one2one).
     * Решаем на общем правиле: активный элемент строит только та
     * категория, в которую канал маршрутизирован.
     *
     * @override
     */
    _computeActiveItem() {
        const thread = this.messaging.discuss.thread;
        if (
            thread &&
            thread.model === 'mail.channel' &&
            thread._getDiscussSidebarCategory() !== this
        ) {
            return clear();
        }
        return this._super();
    },
});
