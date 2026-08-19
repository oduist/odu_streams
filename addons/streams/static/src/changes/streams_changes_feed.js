import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";

import { STREAMS_BUS_CHANGES_UPDATED } from "@streams/core/common/streams_core_service";

import { browser } from "@web/core/browser/browser";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { useBus, useService } from "@web/core/utils/hooks";

/** Размер страницы ленты; тот же, что был в клиенте 15. */
export const STREAMS_CHANGES_PAGE_SIZE = 30;

/**
 * Пауза перед отправкой отметки прочтения: доскролл — событие частое, а
 * прочитанность записи от миллисекунд не зависит.
 */
export const STREAMS_CHANGES_SEEN_DEBOUNCE = 600;

/** Доля видимости элемента, при которой он считается доскролленным. */
const SEEN_THRESHOLD = 0.99;

/**
 * Лента личного канала Changes (§8.3).
 *
 * Элемент ленты — запись-источник, внутри — её изменения «поле: было →
 * стало». Ядровый `Thread` здесь не годится и намеренно не строится
 * (A19): он рисует сообщения, а нужна группировка по записям и
 * фильтрация tracking-значений по персональной подписке, которую считает
 * сервер (`discuss.channel.streams_changes_feed`).
 *
 * Все данные приходят одним RPC и живут в локальном `state`, а не в
 * Store: элемент ленты — не запись Store-модели (сервер собирает его из
 * сообщений, подписки и прав на лету), а держать вторую проекцию тех же
 * сообщений в Store незачем.
 */
export class StreamsChangesFeed extends Component {
    static template = "streams.ChangesFeed";
    static props = ["thread?"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");
        this.state = useState({
            /** @type {Object[]} элементы ленты, от самого свежего */
            items: [],
            isLoading: true,
            isLoadingMore: false,
            hasMore: false,
        });
        /** Наибольший доскролленный `last_message_id`, ещё не отправленный. */
        this._pendingSeenId = 0;
        /** Наибольший `last_message_id`, уже отмеченный прочитанным. */
        this._sentSeenId = 0;
        this._seenTimeout = undefined;
        this._observer = undefined;
        /** Позиция скролла, которую надо вернуть после живого рефреша. */
        this._restoreScrollTop = undefined;
        /** Сколько страниц показано — живой рефреш не должен их терять. */
        this._pageCount = 1;

        onWillStart(() => this.load(this.props.thread));
        onWillUpdateProps((nextProps) => {
            if (nextProps.thread?.id !== this.props.thread?.id) {
                this._resetSeen();
                return this.load(nextProps.thread);
            }
        });
        // сервис `streams.core` ретранслирует пуш шины в `env.bus`, поэтому
        // отписываться вручную не нужно — `useBus` снимет обработчик сам
        useBus(this.env.bus, STREAMS_BUS_CHANGES_UPDATED, ({ detail }) =>
            this.onChangesUpdated(detail)
        );
        useEffect(
            () => this._onRendered(),
            () => [this.state.items]
        );
        onWillUnmount(() => {
            this._disconnectObserver();
            this._clearSeenTimeout();
        });
    }

    // ------------------------------------------------------------------
    // Рендер
    // ------------------------------------------------------------------

    /**
     * Дата изменения в часовом поясе пользователя.
     *
     * Сервер отдаёт `date` в серверном формате UTC
     * (`fields.Datetime.to_string`), поэтому сначала десериализация в
     * luxon-момент пользователя, потом форматирование его локалью.
     *
     * @param {string} value
     * @returns {string}
     */
    formatDate(value) {
        if (!value) {
            return "";
        }
        return formatDateTime(deserializeDateTime(value));
    }

    /**
     * Пустое значение показываем прочерком, иначе «было → стало»
     * превращается в «→ Something» и читается хуже.
     *
     * @param {string|number|boolean} value
     * @returns {string}
     */
    formatValue(value) {
        if (value === false || value === undefined || value === null || value === "") {
            return "—";
        }
        return String(value);
    }

    /**
     * Имя записи кликабельно: из ленты нужно попадать в саму запись.
     *
     * @param {Object} item элемент ленты
     */
    onClickRecord(item) {
        if (!item?.res_model || !item?.res_id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: item.res_model,
            res_id: item.res_id,
            views: [[false, "form"]],
            view_mode: "form",
        });
    }

    // ------------------------------------------------------------------
    // Загрузка и пагинация (D9/G8)
    // ------------------------------------------------------------------

    /**
     * Первая страница ленты; пагинация сбрасывается.
     *
     * @param {import("models").Thread} [thread]
     */
    async load(thread) {
        this.state.isLoading = true;
        try {
            const items = await this._fetch(thread, { limit: STREAMS_CHANGES_PAGE_SIZE });
            this._pageCount = 1;
            this.state.items = items;
            this.state.hasMore = items.length > 0;
        } finally {
            this.state.isLoading = false;
        }
    }

    /**
     * Догрузка страницы вниз по `before_id` (Р8).
     *
     * Кнопкой, а не по доскроллу: так же сделана лента Notifications, а
     * бесконечный скролл здесь конфликтовал бы с отметкой прочтения по
     * доскроллу — самозагружающийся хвост гасил бы непрочитанное.
     */
    async onClickLoadMore() {
        if (this.state.isLoadingMore || !this.state.items.length) {
            return;
        }
        const beforeId = this.state.items.at(-1).last_message_id;
        this.state.isLoadingMore = true;
        try {
            const items = await this._fetch(this.props.thread, {
                limit: STREAMS_CHANGES_PAGE_SIZE,
                beforeId,
            });
            // сервер отсеивает записи, потерявшие подписку или доступ
            // (§8.4), поэтому «страница короче лимита» ещё не означает
            // конец ленты; концом считаем только пустой ответ
            this.state.hasMore = items.length > 0;
            if (items.length) {
                this._pageCount++;
                this.state.items = [...this.state.items, ...items];
            }
        } finally {
            this.state.isLoadingMore = false;
        }
    }

    /**
     * Живое обновление по шине (D7).
     *
     * Тела в payload нет намеренно (`{id: <channel_id>}`) — лента
     * перезапрашивается целиком, зато с учётом прав и подписки.
     *
     * @param {{id: number}} [payload]
     */
    onChangesUpdated(payload) {
        if (!payload || payload.id !== this.props.thread?.id) {
            return;
        }
        this.reload();
    }

    /**
     * Перечитать показанное, не теряя догруженные страницы.
     *
     * Рефреш прилетает по шине, а не по действию пользователя, поэтому
     * позиция скролла восстанавливается: иначе чтение ленты сбивается
     * каждым чужим изменением.
     */
    async reload() {
        this._restoreScrollTop = this.rootRef.el?.scrollTop;
        const items = await this._fetch(this.props.thread, {
            limit: STREAMS_CHANGES_PAGE_SIZE * this._pageCount,
        });
        this.state.items = items;
        this.state.hasMore = items.length > 0;
    }

    /**
     * @private
     * @param {import("models").Thread} [thread]
     * @param {{limit: number, beforeId?: number}} params
     * @returns {Promise<Object[]>}
     */
    async _fetch(thread, { limit, beforeId } = {}) {
        if (!thread?.id) {
            return [];
        }
        const kwargs = { limit };
        if (beforeId) {
            kwargs.before_id = beforeId;
        }
        // silent: лента тянется фоном, спиннер у неё свой
        const items = await this.orm.silent.call(
            "discuss.channel",
            "streams_changes_feed",
            [[thread.id]],
            kwargs
        );
        return items || [];
    }

    // ------------------------------------------------------------------
    // Прочитанность по доскроллу (D5, Р4)
    // ------------------------------------------------------------------

    /**
     * После каждой перерисовки: вернуть скролл (если ждали) и заново
     * навесить наблюдателя — набор непрочитанных элементов изменился.
     *
     * @private
     */
    _onRendered() {
        if (this._restoreScrollTop !== undefined && this.rootRef.el) {
            this.rootRef.el.scrollTop = this._restoreScrollTop;
        }
        this._restoreScrollTop = undefined;
        this._updateObserver();
        return () => this._disconnectObserver();
    }

    /**
     * @private
     */
    _updateObserver() {
        this._disconnectObserver();
        const root = this.rootRef.el;
        if (!root || typeof IntersectionObserver === "undefined") {
            return;
        }
        // наблюдаем только непрочитанные: прочитанные ничего не меняют
        const targets = root.querySelectorAll(".o-streams-ChangesFeed-item.o-unread");
        if (!targets.length) {
            return;
        }
        this._observer = new IntersectionObserver((entries) => this._onIntersect(entries), {
            root,
            // 0 добавлен ради элементов выше окна: до 0.99 они не доходят
            // никогда, и без этого порога наблюдатель по ним молчал бы
            threshold: [0, SEEN_THRESHOLD],
        });
        for (const element of targets) {
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
        const root = this.rootRef.el;
        let candidate = this._pendingSeenId;
        for (const entry of entries) {
            if (!entry.isIntersecting) {
                continue;
            }
            // либо элемент виден целиком, либо он выше окна ленты и занял
            // его целиком — в обоих случаях его прочитали
            const isSeen =
                entry.intersectionRatio >= SEEN_THRESHOLD ||
                (root && entry.intersectionRect.height >= root.clientHeight * SEEN_THRESHOLD);
            if (!isSeen) {
                continue;
            }
            const lastMessageId = parseInt(entry.target.dataset.lastMessageId || "0", 10);
            if (lastMessageId > candidate) {
                candidate = lastMessageId;
            }
        }
        if (candidate <= this._sentSeenId) {
            return;
        }
        this._pendingSeenId = candidate;
        this._clearSeenTimeout();
        this._seenTimeout = browser.setTimeout(
            () => this._sendSeen(),
            STREAMS_CHANGES_SEEN_DEBOUNCE
        );
    }

    /**
     * Отметить прочитанным до самой свежей доскролленной записи.
     *
     * @private
     */
    async _sendSeen() {
        this._seenTimeout = undefined;
        const thread = this.props.thread;
        const lastMessageId = this._pendingSeenId;
        if (!thread?.id || lastMessageId <= this._sentSeenId) {
            return;
        }
        this._sentSeenId = lastMessageId;
        const result = await this.orm.silent.call(
            "discuss.channel",
            "streams_mark_read",
            [[thread.id]],
            { last_message_id: lastMessageId }
        );
        if (!result) {
            // участника больше нет (канал покинули в соседней вкладке) —
            // ронять доскролл из-за этого незачем
            return;
        }
        for (const item of this.state.items) {
            if (item.unread && item.last_message_id <= lastMessageId) {
                item.unread = false;
            }
        }
        // новый массив — чтобы перевесить наблюдателя на оставшиеся
        // непрочитанные элементы
        this.state.items = [...this.state.items];
        // счётчик канала считает сервер; берём его из ответа, чтобы бейдж
        // в сайдбаре не ждал отдельного пуша
        const member = thread.self_member_id;
        if (member && typeof result.unread === "number") {
            member.message_unread_counter = result.unread;
        }
    }

    /**
     * @private
     */
    _clearSeenTimeout() {
        if (this._seenTimeout) {
            browser.clearTimeout(this._seenTimeout);
            this._seenTimeout = undefined;
        }
    }

    /**
     * @private
     */
    _resetSeen() {
        this._clearSeenTimeout();
        this._pendingSeenId = 0;
        this._sentSeenId = 0;
    }
}
