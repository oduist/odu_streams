/** @odoo-module **/

import {
    registerFieldPatchModel,
    registerInstancePatchModel,
} from '@mail/model/model_core';
import { one2one } from '@mail/model/model_field';

const PATCH_ID = 'streams/static/src/models/discuss.js';

registerFieldPatchModel('mail.discuss', PATCH_ID, {
    /**
     * Категория сайдбара «Messages» — каналы записей (§11.3).
     */
    categoryStreams: one2one('mail.discuss_sidebar_category', {
        inverse: 'discussAsStreams',
        isCausal: true,
    }),
});

registerInstancePatchModel('mail.discuss', PATCH_ID, {
    /**
     * У личного канала Changes своя лента (§8.3), ядровый ThreadView для
     * него не строится: иначе он молча вычитывал бы все сообщения канала
     * (`/mail/channel/messages`) ради вида, который даже не отрисуется.
     *
     * @override
     */
    _computeHasThreadView() {
        const kind = this.thread && this.thread.streamsChannelKind;
        if (kind === 'changes' || kind === 'notifications') {
            return false;
        }
        return this._super();
    },
    /**
     * Быстрый фильтр не должен искать в свёрнутой категории.
     *
     * @override
     */
    onInputQuickSearch(value) {
        if (!this.sidebarQuickSearchValue) {
            if (this.categoryStreams) {
                this.categoryStreams.open();
            }
        }
        return this._super(value);
    },
});
