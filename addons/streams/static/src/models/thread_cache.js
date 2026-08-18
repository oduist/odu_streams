/** @odoo-module **/

import { registerInstancePatchModel } from '@mail/model/model_core';
import { replace } from '@mail/model/model_field_command';

const PATCH_ID = 'streams/static/src/models/thread_cache.js';

registerInstancePatchModel('mail.thread_cache', PATCH_ID, {
    /**
     * Фильтры потоков — настройка отображения, а не подписка (§6): лента
     * канала грузится целиком, скрывается только рендер. Сообщения
     * «прочее» (streamsKind не задан) показываются всегда.
     *
     * @override
     */
    _computeOrderedNonEmptyMessages() {
        const command = this._super();
        const thread = this.thread;
        if (!thread || thread.streamsChannelKind !== 'record') {
            return command;
        }
        const filters = thread.streamsFilters || {};
        const messages = (command && command.value) || [];
        return replace(messages.filter(message => {
            const kind = message.streamsKind;
            return !kind || filters[kind] !== false;
        }));
    },
    /**
     * Домен «прочитать всё» в канале записи обязан покрывать проекции:
     * ядровый строится по (model, res_id) и видит только собственные
     * сообщения канала.
     *
     * @override
     */
    _onChangeMarkAllAsRead() {
        const thread = this.thread;
        if (!thread || thread.streamsChannelKind !== 'record') {
            return this._super();
        }
        if (this.messaging.currentGuest) {
            return;
        }
        if (!this.isMarkAllAsReadRequested || !this.isLoaded || this.isLoading) {
            // ждём смены состояния, как в ядре
            return;
        }
        this.update({ isMarkAllAsReadRequested: false });
        if (thread.isTemporary || this.threadViews.length === 0) {
            return;
        }
        this.messaging.models['mail.message'].markAllAsRead([
            '|',
            '&', ['model', '=', 'mail.channel'], ['res_id', '=', thread.id],
            ['stream_channel_ids', 'in', [thread.id]],
        ]);
    },
});
