import { Component, onWillDestroy, onWillStart, useEffect, useRef, useState } from "@odoo/owl";

import { browser } from "@web/core/browser/browser";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { useBus, useService } from "@web/core/utils/hooks";

import {
    STREAMS_BUS_NOTIFY_NEW,
    STREAMS_BUS_NOTIFY_UPDATE,
} from "../core/common/streams_core_service";
import { StreamsNotifyCard } from "./streams_notify_card";

const { DateTime } = luxon;

/** Страница ленты; тот же лимит зажимает сервер. */
const FEED_LIMIT = 30;

/** Доскролл до карточки — событие частое, прочитанность не спешит (G3). */
const READ_DEBOUNCE_DELAY = 500;

/**
 * Лента личного канала Notifications (§12.5).
 *
 * Ядровый ThreadView здесь неприменим: уведомления — не `mail.message`,
 * сообщений в этом канале не бывает вовсе (A19). Отсюда своя пагинация
 * по `before_id`, две вкладки и прочитанность по доскроллу.
 */
export class StreamsNotifyFeed extends Component {
    static components = { StreamsNotifyCard };
    // как в ядровом `DiscussContent`: тред — Store-запись, строгая
    // проверка типа на ней только мешает
    static props = ["thread?"];
    static template = "streams.NotifyFeed";

    setup() {
        this.orm = useService("orm");
        this.streamsCore = useService("streams.core");
        this.store = useService("mail.store");
        this.settings = useState(this.store.settings);
        this.listRef = useRef("list");
        this.state = useState({
            box: "received",
            /** @type {Object[]} элементы `_streams_payload` */
            items: [],
            isLoading: true,
            hasMore: false,
        });
        /** Уже отправленные на сервер id — второй раз не шлём. */
        this._markedRead = new Set();
        /** @type {number[]} */
        this._pendingRead = [];
        this._readTimer = null;
        this._observer = null;

        onWillStart(() => this._load());
        useBus(this.env.bus, STREAMS_BUS_NOTIFY_NEW, ({ detail }) =>
            this._onNotifyNew(detail)
        );
        useBus(this.env.bus, STREAMS_BUS_NOTIFY_UPDATE, ({ detail }) =>
            this._onNotifyUpdate(detail)
        );
        useEffect(
            () => {
                this._updateObserver();
                return () => this._disconnectObserver();
            },
            () => [this.state.items.length, this.state.box, this.state.isLoading]
        );
        onWillDestroy(() => {
            this._disconnectObserver();
            if (this._readTimer) {
                browser.clearTimeout(this._readTimer);
            }
        });
    }

    /** @type {boolean} */
    get isSoundMuted() {
        return Boolean(this.settings.is_streams_notify_sound_muted);
    }

    /** @param {Object} item */
    isUnread(item) {
        return this.state.box === "received" && !item.read_date;
    }

    /**
     * @param {string|false} value
     * @returns {string}
     */
    formatReadDate(value) {
        if (!value) {
            return "";
        }
        return deserializeDateTime(value).toLocaleString(DateTime.DATETIME_MED);
    }

    // ------------------------------------------------------------
    // ДЕЙСТВИЯ
    // ------------------------------------------------------------

    onClickBox(box) {
        if (box === this.state.box) {
            return;
        }
        this.state.box = box;
        this._markedRead = new Set();
        this._pendingRead = [];
        this._load();
    }

    onClickNew() {
        // без записи-источника (F10): уведомление «просто так»
        this.streamsCore.openNotifyComposer();
    }

    onClickReply(item) {
        this.streamsCore.replyToNotify(item.id);
    }

    onClickMute() {
        this.streamsCore.toggleNotifySoundMute();
    }

    onClickLoadMore() {
        this._load({ append: true });
    }

    // ------------------------------------------------------------
    // ДАННЫЕ
    // ------------------------------------------------------------

    async _load({ append = false } = {}) {
        this.state.isLoading = !append;
        const kwargs = { box: this.state.box, limit: FEED_LIMIT };
        if (append && this.state.items.length) {
            kwargs.before_id = this.state.items.at(-1).id;
        }
        let items;
        try {
            items = await this.orm.silent.call(
                "mail.notify",
                "streams_notify_feed",
                [],
                kwargs
            );
        } finally {
            this.state.isLoading = false;
        }
        items = items || [];
        // записи Store — общий источник правды для попапов и ленты;
        // сама лента держит плоские payload'ы, как отдаёт сервер
        for (const item of items) {
            this.store["mail.notify"].insert(item);
        }
        this.state.items = append ? [...this.state.items, ...items] : items;
        this.state.hasMore = items.length === FEED_LIMIT;
    }

    /**
     * Живая вставка нового уведомления в открытую ленту (G5).
     *
     * @param {Object} payload
     */
    _onNotifyNew(payload) {
        if (this.state.box !== "received" || !payload?.id) {
            return;
        }
        if (this.state.items.some((item) => item.id === payload.id)) {
            return;
        }
        const { counter, ...notifyData } = payload;
        this.state.items = [notifyData, ...this.state.items];
    }

    /**
     * Точечное обновление карточки: транскрипт либо отметка получателя (G6).
     *
     * @param {Object} payload
     */
    _onNotifyUpdate(payload) {
        if (!payload?.id) {
            return;
        }
        const index = this.state.items.findIndex((item) => item.id === payload.id);
        if (index === -1) {
            return;
        }
        const { recipient, ...patchData } = payload;
        const item = { ...this.state.items[index], ...patchData };
        if (recipient && item.recipients) {
            item.recipients = item.recipients.map((row) =>
                row.user_id === recipient.user_id ? { ...row, ...recipient } : row
            );
        }
        // новый массив: реактивность ловит присваивание элемента, а
        // правку полей вложенного объекта — нет
        this.state.items = [
            ...this.state.items.slice(0, index),
            item,
            ...this.state.items.slice(index + 1),
        ];
    }

    // ------------------------------------------------------------
    // ПРОЧИТАННОСТЬ ПО ДОСКРОЛЛУ (G3)
    // ------------------------------------------------------------

    _updateObserver() {
        this._disconnectObserver();
        const root = this.listRef.el;
        if (!root || this.state.box !== "received" || typeof IntersectionObserver === "undefined") {
            return;
        }
        // глобальный IntersectionObserver: в `@web/core/browser/browser`
        // его нет, ядро (`useVisible`) берёт его так же
        this._observer = new IntersectionObserver(
            (entries) => this._onIntersect(entries),
            { root, threshold: 0.9 }
        );
        for (const element of root.querySelectorAll(".o-streams-NotifyFeed-item.o-unread")) {
            this._observer.observe(element);
        }
    }

    _disconnectObserver() {
        this._observer?.disconnect();
        this._observer = null;
    }

    _onIntersect(entries) {
        for (const entry of entries) {
            if (!entry.isIntersecting) {
                continue;
            }
            const notifyId = parseInt(entry.target.dataset.notifyId || "0", 10);
            if (
                !notifyId ||
                this._markedRead.has(notifyId) ||
                this._pendingRead.includes(notifyId)
            ) {
                continue;
            }
            this._pendingRead.push(notifyId);
        }
        if (!this._pendingRead.length) {
            return;
        }
        if (this._readTimer) {
            browser.clearTimeout(this._readTimer);
        }
        this._readTimer = browser.setTimeout(
            () => this._flushRead(),
            READ_DEBOUNCE_DELAY
        );
    }

    async _flushRead() {
        this._readTimer = null;
        const notifyIds = this._pendingRead;
        this._pendingRead = [];
        if (!notifyIds.length) {
            return;
        }
        for (const notifyId of notifyIds) {
            this._markedRead.add(notifyId);
        }
        await this.streamsCore.markNotifyRead(notifyIds);
        this.state.items = this.state.items.map((item) =>
            notifyIds.includes(item.id) && !item.read_date
                ? { ...item, read_date: this.store["mail.notify"].get(item.id)?.read_date }
                : item
        );
    }
}
