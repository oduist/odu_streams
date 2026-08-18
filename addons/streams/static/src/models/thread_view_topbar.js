/** @odoo-module **/

import { registerInstancePatchModel } from '@mail/model/model_core';

import { STREAMS_FILTER_ORDER } from '@streams/js/streams_filters';
import { withStreamsNotifyService } from '@streams/js/notify_bridge';

const PATCH_ID = 'streams/static/src/models/thread_view_topbar.js';

registerInstancePatchModel('mail.thread_view_topbar', PATCH_ID, {
    /**
     * @override
     */
    _created() {
        // биндинг обязателен, пока OWL не умеет стрелки в обработчиках
        this.onClickStreamsFilter = this.onClickStreamsFilter.bind(this);
        this.onClickStreamsNotify = this.onClickStreamsNotify.bind(this);
        this.onClickStreamsInvite = this.onClickStreamsInvite.bind(this);
        return this._super();
    },
    /**
     * Приглашение клиента из канала записи (§9.2, Б1).
     */
    onClickStreamsInvite() {
        const thread = this.thread;
        if (!thread || thread.streamsChannelKind !== 'record') {
            return;
        }
        this.env.bus.trigger('do-action', {
            action: {
                type: 'ir.actions.act_window',
                name: this.env._t("Invite a customer to this chat"),
                res_model: 'streams.guest.invite.wizard',
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'new',
                res_id: false,
                context: { default_channel_id: thread.id },
            },
        });
    },
    /**
     * Notify из канала записи (§11.2): та же форма, что и в чаттере,
     * запись берётся из самого канала.
     */
    onClickStreamsNotify() {
        const thread = this.thread;
        if (!thread || !thread.streamsResModel || !thread.streamsResId) {
            return;
        }
        withStreamsNotifyService(service => service.openComposer({
            resModel: thread.streamsResModel,
            resId: thread.streamsResId,
        }));
    },
    /**
     * Тумблеры потоков канала записи (§6).
     *
     * @returns {Object[]}
     */
    streamsFilterItems() {
        const labels = {
            activity: this.env._t("Activities"),
            change: this.env._t("Changes"),
            comment: this.env._t("Comments"),
            message: this.env._t("Customers"),
            note: this.env._t("Notes"),
        };
        return STREAMS_FILTER_ORDER.map(key => ({ key, label: labels[key] }));
    },
    /**
     * @param {MouseEvent} ev
     */
    onClickStreamsFilter(ev) {
        ev.stopPropagation();
        const thread = this.thread;
        const key = ev.currentTarget.dataset.streamsFilter;
        if (!thread || !key) {
            return;
        }
        const filters = Object.assign({}, thread.streamsFilters);
        filters[key] = !filters[key];
        thread.update({ streamsFilters: filters });
        this.env.services.rpc({
            model: 'mail.channel',
            method: 'streams_set_filters',
            args: [[thread.id], { [key]: filters[key] }],
        }, { shadow: true });
    },
});
