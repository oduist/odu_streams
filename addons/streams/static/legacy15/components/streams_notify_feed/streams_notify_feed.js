/** @odoo-module **/

import { registerMessagingComponent } from '@mail/utils/messaging_component';

import { withStreamsNotifyService } from '@streams/js/notify_bridge';

const { Component } = owl;
const { useState } = owl.hooks;

// доскролл до карточки — событие частое, прочитанность от миллисекунд
// не зависит
const READ_DEBOUNCE_DELAY = 500;
const FEED_LIMIT = 30;

/**
 * Лента личного канала Notifications (§12.5).
 *
 * Уведомления — не `mail.message`, поэтому ядровый ThreadView здесь
 * неприменим: две вкладки Received/Sent, своя пагинация по `before_id`
 * и прочитанность по доскроллу через `streams_notify_mark_read`.
 */
export class StreamsNotifyFeed extends Component {

    setup() {
        super.setup();
        this.state = useState({
            box: 'received',
            items: [],
            isLoading: true,
            hasMore: false,
            isSoundMuted: false,
        });
        this._service = undefined;
        this._observer = undefined;
        this._readTimeout = undefined;
        this._pendingRead = [];
        this._markedRead = new Set();
        this._onIntersect = this._onIntersect.bind(this);
        this._onServiceUpdate = this._onServiceUpdate.bind(this);
        withStreamsNotifyService(service => {
            this._service = service;
            this.state.isSoundMuted = service.state.isSoundMuted;
            service.bus.on('NOTIFY-NEW', this, this._onNotifyNew);
            service.bus.on('NOTIFY-UPDATE', this, this._onNotifyUpdate);
        });
    }

    async willStart() {
        await this._load();
    }

    mounted() {
        this._updateObserver();
    }

    patched() {
        this._updateObserver();
    }

    willUnmount() {
        if (this._service) {
            this._service.bus.off('NOTIFY-NEW', this);
            this._service.bus.off('NOTIFY-UPDATE', this);
        }
        this._disconnectObserver();
        if (this._readTimeout) {
            clearTimeout(this._readTimeout);
            this._readTimeout = undefined;
        }
    }

    //----------------------------------------------------------------------
    // Публичное
    //----------------------------------------------------------------------

    get thread() {
        return this.messaging.models['mail.thread'].get(
            this.props.threadLocalId);
    }

    formatDate(value) {
        if (!value) {
            return '';
        }
        return moment.utc(value).local().format('L LT');
    }

    formatDuration(seconds) {
        const total = Math.max(parseInt(seconds || 0, 10), 0);
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return minutes + ':' + (rest < 10 ? '0' : '') + rest;
    }

    attachmentUrl(attachmentId) {
        return '/web/content/' + attachmentId + '?download=true';
    }

    voiceUrl(attachmentId) {
        return '/web/content/' + attachmentId;
    }

    //----------------------------------------------------------------------
    // Действия
    //----------------------------------------------------------------------

    onClickBox(ev) {
        const box = ev.currentTarget.dataset.box;
        if (!box || box === this.state.box) {
            return;
        }
        this.state.box = box;
        this._markedRead = new Set();
        this._load();
    }

    onClickNew() {
        if (this._service) {
            this._service.openComposer({});
        }
    }

    onClickReply(ev) {
        const id = parseInt(ev.currentTarget.dataset.notifyId, 10);
        const item = this.state.items.find(entry => entry.id === id);
        if (item && this._service) {
            this._service.reply(item);
        }
    }

    onClickRecord(ev) {
        ev.preventDefault();
        const { resModel, resId } = ev.currentTarget.dataset;
        if (this._service) {
            this._service.openRecord(resModel, parseInt(resId, 10));
        }
    }

    onClickMute() {
        if (!this._service) {
            return;
        }
        this._service.toggleMute();
        this.state.isSoundMuted = this._service.state.isSoundMuted;
    }

    onClickLoadMore() {
        this._load({ append: true });
    }

    //----------------------------------------------------------------------
    // Данные
    //----------------------------------------------------------------------

    async _load({ append = false } = {}) {
        this.state.isLoading = !append;
        const kwargs = { box: this.state.box, limit: FEED_LIMIT };
        if (append && this.state.items.length) {
            kwargs.before_id = this.state.items[this.state.items.length - 1].id;
        }
        let items = [];
        try {
            items = await this.env.services.rpc({
                model: 'mail.notify',
                method: 'streams_notify_feed',
                args: [],
                kwargs: kwargs,
            }, { shadow: true });
        } catch (error) {
            this.state.isLoading = false;
            throw error;
        }
        items = items || [];
        this.state.items = append ? this.state.items.concat(items) : items;
        this.state.hasMore = items.length === FEED_LIMIT;
        this.state.isLoading = false;
        this._syncUnreadCounter();
    }

    /**
     * Счётчик канала считается по уведомлениям, а не по сообщениям:
     * сообщений в этом канале не бывает вовсе.
     *
     * @private
     */
    _syncUnreadCounter() {
        const thread = this.thread;
        if (!thread || !this._service) {
            return;
        }
        const counter = this._service.state.counter;
        if (thread.serverMessageUnreadCounter !== counter) {
            thread.update({ serverMessageUnreadCounter: counter });
        }
    }

    /**
     * @private
     */
    _onNotifyNew(payload) {
        if (this.state.box !== 'received' || !payload) {
            return;
        }
        if (this.state.items.some(item => item.id === payload.id)) {
            return;
        }
        this.state.items.unshift(payload);
        this._syncUnreadCounter();
    }

    /**
     * @private
     */
    _onNotifyUpdate(payload) {
        if (!payload) {
            return;
        }
        const item = this.state.items.find(entry => entry.id === payload.id);
        if (!item) {
            return;
        }
        Object.assign(item, payload);
        if (payload.recipient && item.recipients) {
            const row = item.recipients.find(
                entry => entry.user_id === payload.recipient.user_id);
            if (row) {
                row.read_date = payload.recipient.read_date;
            }
        }
        this.render();
    }

    /**
     * @private
     */
    _onServiceUpdate() {
        this.render();
    }

    //----------------------------------------------------------------------
    // Прочитанность по скроллу (§12.5)
    //----------------------------------------------------------------------

    _updateObserver() {
        this._disconnectObserver();
        if (!this.el || this.state.box !== 'received'
                || typeof IntersectionObserver === 'undefined') {
            return;
        }
        this._observer = new IntersectionObserver(this._onIntersect, {
            root: this.el,
            threshold: 0.9,
        });
        for (const element of this.el.querySelectorAll(
                '.o_StreamsNotifyFeed_item.o-unread')) {
            this._observer.observe(element);
        }
    }

    _disconnectObserver() {
        if (this._observer) {
            this._observer.disconnect();
            this._observer = undefined;
        }
    }

    _onIntersect(entries) {
        for (const entry of entries) {
            if (!entry.isIntersecting) {
                continue;
            }
            const id = parseInt(entry.target.dataset.notifyId || '0', 10);
            if (!id || this._markedRead.has(id)
                    || this._pendingRead.includes(id)) {
                continue;
            }
            this._pendingRead.push(id);
        }
        if (!this._pendingRead.length) {
            return;
        }
        if (this._readTimeout) {
            clearTimeout(this._readTimeout);
        }
        this._readTimeout = setTimeout(
            () => this._sendRead(), READ_DEBOUNCE_DELAY);
    }

    async _sendRead() {
        this._readTimeout = undefined;
        const ids = this._pendingRead;
        this._pendingRead = [];
        if (!ids.length || !this._service) {
            return;
        }
        for (const id of ids) {
            this._markedRead.add(id);
        }
        await this._service.markRead(ids);
        for (const item of this.state.items) {
            if (ids.includes(item.id)) {
                item.read_date = item.read_date || 'now';
            }
        }
        this._syncUnreadCounter();
        this.render();
    }
}

StreamsNotifyFeed.props = {
    threadLocalId: String,
};
StreamsNotifyFeed.template = 'streams.NotifyFeed';

registerMessagingComponent(StreamsNotifyFeed);
