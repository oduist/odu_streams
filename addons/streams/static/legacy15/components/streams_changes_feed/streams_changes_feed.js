/** @odoo-module **/

import { registerMessagingComponent } from '@mail/utils/messaging_component';

const { Component } = owl;
const { useState } = owl.hooks;

// пауза перед отправкой seen: доскролл до элемента — событие частое,
// а прочитанность записи от миллисекунд не зависит
const SEEN_DEBOUNCE_DELAY = 600;

/**
 * Лента личного канала Changes (§8.3).
 *
 * Элемент ленты — запись-источник, внутри — её изменения «поле: было →
 * стало». Стандартный ThreadView здесь не годится: он рисует сообщения,
 * а нам нужна группировка по записям и фильтрация tracking-значений по
 * подписке, которую считает сервер (`streams_changes_feed`).
 */
export class StreamsChangesFeed extends Component {

    setup() {
        super.setup();
        this.state = useState({ items: [], isLoading: true });
        this.onClickRecord = this.onClickRecord.bind(this);
        this._onChangesUpdated = this._onChangesUpdated.bind(this);
        this._onIntersect = this._onIntersect.bind(this);
        this._observer = undefined;
        this._seenTimeout = undefined;
        this._pendingSeenId = 0;
        this._sentSeenId = 0;
    }

    async willStart() {
        await this._loadFeed(this.props.threadLocalId);
    }

    async willUpdateProps(nextProps) {
        if (nextProps.threadLocalId !== this.props.threadLocalId) {
            this._sentSeenId = 0;
            this._pendingSeenId = 0;
            await this._loadFeed(nextProps.threadLocalId);
        }
    }

    mounted() {
        this.messaging.messagingBus.on(
            'streams-changes-updated', this, this._onChangesUpdated);
        this._updateObserver();
    }

    patched() {
        this._updateObserver();
    }

    willUnmount() {
        this.messaging.messagingBus.off('streams-changes-updated', this);
        this._disconnectObserver();
        if (this._seenTimeout) {
            clearTimeout(this._seenTimeout);
            this._seenTimeout = undefined;
        }
    }

    //----------------------------------------------------------------------
    // Публичное
    //----------------------------------------------------------------------

    /**
     * @returns {mail.thread|undefined}
     */
    get thread() {
        return this.messaging.models['mail.thread'].get(this.props.threadLocalId);
    }

    /**
     * Дата изменения в часовом поясе пользователя.
     *
     * @param {string} value
     * @returns {string}
     */
    formatDate(value) {
        if (!value) {
            return '';
        }
        return moment.utc(value).local().format('L LT');
    }

    /**
     * Пустое значение поля показываем прочерком, иначе «было → стало»
     * превращается в «→ Something» и читается хуже.
     *
     * @param {string|number|boolean} value
     * @returns {string}
     */
    formatValue(value) {
        if (value === false || value === undefined || value === null || value === '') {
            return '—';
        }
        return String(value);
    }

    /**
     * @param {MouseEvent} ev
     */
    onClickRecord(ev) {
        ev.preventDefault();
        const { resModel, resId } = ev.currentTarget.dataset;
        if (!resModel || !resId) {
            return;
        }
        this.env.bus.trigger('do-action', {
            action: {
                type: 'ir.actions.act_window',
                res_model: resModel,
                res_id: parseInt(resId, 10),
                views: [[false, 'form']],
                view_mode: 'form',
            },
        });
    }

    //----------------------------------------------------------------------
    // Приватное
    //----------------------------------------------------------------------

    /**
     * @private
     * @param {string} threadLocalId
     */
    async _loadFeed(threadLocalId) {
        const thread = this.messaging.models['mail.thread'].get(threadLocalId);
        if (!thread || !thread.id) {
            this.state.items = [];
            this.state.isLoading = false;
            return;
        }
        this.state.isLoading = true;
        let items = [];
        try {
            items = await this.env.services.rpc({
                model: 'mail.channel',
                method: 'streams_changes_feed',
                args: [[thread.id]],
                kwargs: { limit: 30 },
            }, { shadow: true });
        } catch (error) {
            this.state.isLoading = false;
            throw error;
        }
        this.state.items = items || [];
        this.state.isLoading = false;
        this._syncUnreadCounter();
    }

    /**
     * Счётчик канала считается по записям (§8.3), а серверное значение
     * клиент пересчитать не может: сообщений изменений в его памяти нет.
     * Лента их уже посчитала — переносим результат в модель.
     *
     * @private
     */
    _syncUnreadCounter() {
        const thread = this.thread;
        if (!thread) {
            return;
        }
        const unread = this.state.items.filter(item => item.unread).length;
        if (thread.serverMessageUnreadCounter !== unread) {
            thread.update({ serverMessageUnreadCounter: unread });
        }
    }

    /**
     * @private
     */
    _onChangesUpdated(payload) {
        const thread = this.thread;
        if (!thread || !payload || payload.id !== thread.id) {
            return;
        }
        this._loadFeed(this.props.threadLocalId);
    }

    //----------------------------------------------------------------------
    // Прочитанность при скролле (§8.3)
    //----------------------------------------------------------------------

    /**
     * @private
     */
    _updateObserver() {
        this._disconnectObserver();
        if (!this.el || typeof IntersectionObserver === 'undefined') {
            return;
        }
        this._observer = new IntersectionObserver(this._onIntersect, {
            root: this.el,
            threshold: 0.99,
        });
        for (const element of this.el.querySelectorAll('.o_StreamsChangesFeed_item')) {
            this._observer.observe(element);
        }
    }

    /**
     * @private
     */
    _disconnectObserver() {
        if (this._observer) {
            this._observer.disconnect();
            this._observer = undefined;
        }
    }

    /**
     * @private
     * @param {IntersectionObserverEntry[]} entries
     */
    _onIntersect(entries) {
        let candidate = this._pendingSeenId;
        for (const entry of entries) {
            if (!entry.isIntersecting) {
                continue;
            }
            const lastMessageId = parseInt(
                entry.target.dataset.lastMessageId || '0', 10);
            if (lastMessageId > candidate) {
                candidate = lastMessageId;
            }
        }
        if (candidate <= this._sentSeenId) {
            return;
        }
        this._pendingSeenId = candidate;
        if (this._seenTimeout) {
            clearTimeout(this._seenTimeout);
        }
        this._seenTimeout = setTimeout(() => this._sendSeen(), SEEN_DEBOUNCE_DELAY);
    }

    /**
     * @private
     */
    async _sendSeen() {
        this._seenTimeout = undefined;
        const thread = this.thread;
        const lastMessageId = this._pendingSeenId;
        if (!thread || !thread.id || lastMessageId <= this._sentSeenId) {
            return;
        }
        this._sentSeenId = lastMessageId;
        await this.env.services.rpc({
            route: '/mail/channel/set_last_seen_message',
            params: {
                channel_id: thread.id,
                last_message_id: lastMessageId,
            },
        }, { shadow: true });
        for (const item of this.state.items) {
            if (item.last_message_id <= lastMessageId) {
                item.unread = false;
            }
        }
        this._syncUnreadCounter();
    }
}

StreamsChangesFeed.props = {
    threadLocalId: String,
};
StreamsChangesFeed.template = 'streams.ChangesFeed';

registerMessagingComponent(StreamsChangesFeed);
