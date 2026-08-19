import { browser } from "@web/core/browser/browser";
import { serializeDateTime } from "@web/core/l10n/dates";
import { patch } from "@web/core/utils/patch";

import {
    StreamsCore,
    STREAMS_NOTIFY_DEFAULT_TIMEOUT,
} from "../core/common/streams_core_service";
import { StreamsNotifyComposer } from "./streams_notify_composer";

const { DateTime } = luxon;

/** Отметка «попап показан» шлётся пачкой (E6): серверу важен только факт. */
export const POPUP_SHOWN_DELAY = 500;

/** Звук уведомления. Имя из ядрового `mail.sound_effects` (19). */
const NOTIFY_SOUND = "new-message";

/** Фолбэк-звук, если сервис звуков ещё не поднялся (тот же файл ядра). */
const NOTIFY_SOUND_URL = "/mail/static/src/audio/new-message";

/**
 * Подсистема Notify поверх фундамента WP1 (§12).
 *
 * Подписки шины заводит `streams_core_service.js`; здесь наращивается
 * только поведение: стек попапов, звук, прочитанность, переходы и
 * диалог отправки. Каждый обработчик шины вызывает `super`, поэтому
 * ретрансляция в `env.bus` (на неё живут лента и колокол) сохраняется.
 *
 * Сервисы берутся из `this.env.services` по месту вызова, а не в
 * конструкторе: `streams.core` стартует в общем графе сервисов, и
 * порядок относительно `orm`/`dialog`/`mail.sound_effects` не задан.
 */
patch(StreamsCore.prototype, {
    setup() {
        /**
         * Открытые попапы — копии payload'ов, а не записи Store.
         *
         * Копия нужна ровно потому, что попап живёт своей жизнью: его
         * закрывают, его таймер ставят на паузу, — и всё это не должно
         * мутировать общую запись `mail.notify`, из которой рисуется
         * лента. Обновления по шине применяются к обоим (см. onNotifyUpdate).
         *
         * @type {Object[]}
         */
        this.notifyState.popups = [];
        /** Позиция в стеке sticky-попапов (E5). */
        this.notifyState.stickyIndex = 0;
        /** @type {Map<number, number>} id уведомления → id таймера */
        this._popupTimers = new Map();
        /** @type {number[]} */
        this._shownQueue = [];
        this._shownTimer = null;
        this._fallbackAudio = null;
        // состояние обязано существовать до super: WP1 в конце setup()
        // применяет init-payload, а он уже раскладывает попапы
        super.setup(...arguments);
    },

    // ------------------------------------------------------------
    // ШИНА
    // ------------------------------------------------------------

    /** @override новое уведомление — попап плюс звук (E3, E8). */
    onNotifyNew(payload) {
        super.onNotifyNew(payload);
        if (this._drainPending()) {
            this.playNotifySound();
        }
        this._syncNotifyChannelCounter();
    },

    /** @override счётчик — ещё и в бейдж канала в сайдбаре (A13). */
    onNotifyCounter(payload) {
        super.onNotifyCounter(payload);
        this._syncNotifyChannelCounter();
    },

    /**
     * Продублировать счётчик в участника канала Notifications.
     *
     * Бейдж канала в сайдбаре читает `member.message_unread_counter`;
     * сервер считает его из непрочитанных уведомлений (ветка
     * `notifications` в `_compute_message_unread`), но пересчитанное
     * значение само в Store не приезжает — по шине идёт только
     * `streams.notify/counter`. Это НЕ костыль `_syncUnreadCounter` из
     * 15 (там счётчик выводили из содержимого ленты): здесь применяется
     * авторитетное серверное число из пуша.
     */
    _syncNotifyChannelCounter() {
        const channelId = this.notifyState.channelId;
        if (!channelId) {
            return;
        }
        const thread = this.store.Thread.get({
            model: "discuss.channel",
            id: channelId,
        });
        const member = thread?.self_member_id;
        if (member) {
            member.message_unread_counter = this.notifyState.counter;
        }
    },

    /**
     * @override точечная правка: транскрипт либо `read_date` получателя.
     *
     * super кладёт патч в запись Store и ретранслирует в `env.bus` (там
     * его подхватит лента). Здесь остаётся синхронизировать открытые
     * попапы — «Transcribing…» должно смениться текстом прямо в карточке.
     */
    onNotifyUpdate(payload) {
        super.onNotifyUpdate(payload);
        if (!payload?.id) {
            return;
        }
        const popup = this.notifyState.popups.find((item) => item.id === payload.id);
        if (popup) {
            const patchData = { ...payload };
            // `recipient` — состояние доставки для вкладки Sent, попапу
            // получателя оно не принадлежит
            delete patchData.recipient;
            Object.assign(popup, patchData);
        }
        // отметки прочтения получателей нужны вкладке Sent, а она читает
        // записи Store — доложим их туда, WP1 их намеренно отбрасывает
        if (payload.recipient) {
            this._mergeRecipient(payload.id, payload.recipient);
        }
    },

    /** @override накопившиеся попапы (E7) всплывают на старте клиента. */
    applyInitPayload(payload) {
        super.applyInitPayload(payload);
        if (this._drainPending()) {
            // один звук на всю пачку: логин после выходных не должен
            // превращаться в очередь из двадцати сигналов
            this.playNotifySound();
        }
    },

    /**
     * Слить `read_date` получателя в запись Store (вкладка Sent).
     *
     * @param {number} notifyId
     * @param {{user_id: number, name: string, read_date: string|false}} recipient
     */
    _mergeRecipient(notifyId, recipient) {
        const record = this.store["mail.notify"].get(notifyId);
        if (!record?.recipients?.length) {
            return;
        }
        // новый массив, а не мутация на месте: `recipients` — Attr-поле,
        // реактивность ловит присваивание, а не правку элемента
        record.recipients = record.recipients.map((row) =>
            row.user_id === recipient.user_id ? { ...row, ...recipient } : row
        );
    },

    // ------------------------------------------------------------
    // СТЕК ПОПАПОВ (§12.4)
    // ------------------------------------------------------------

    /**
     * Показать всё, что WP1 сложил в очередь непоказанных.
     *
     * @returns {boolean} были ли новые попапы
     */
    _drainPending() {
        const pending = this.notifyState.pending.splice(0);
        let shown = false;
        for (const notifyData of pending) {
            if (this._pushPopup(notifyData)) {
                shown = true;
            }
        }
        return shown;
    },

    /**
     * @param {Object} notifyData элемент `_streams_payload`
     * @returns {boolean} попап новый (а не обновление уже открытого)
     */
    _pushPopup(notifyData) {
        if (!notifyData?.id) {
            return false;
        }
        const known = this.notifyState.popups.find((item) => item.id === notifyData.id);
        if (known) {
            Object.assign(known, notifyData);
            return false;
        }
        const popup = { ...notifyData };
        this.notifyState.popups.push(popup);
        if (popup.is_sticky) {
            // самый свежий sticky показывается сразу (E5)
            this.notifyState.stickyIndex = this.stickyPopups.length - 1;
        } else {
            this._startPopupTimer(popup);
        }
        this._queuePopupShown(popup.id);
        return true;
    },

    /** @type {Object[]} только sticky-попапы, в порядке прихода. */
    get stickyPopups() {
        return this.notifyState.popups.filter((item) => item.is_sticky);
    },

    /** @type {Object[]} попапы, которые гаснут сами. */
    get transientPopups() {
        return this.notifyState.popups.filter((item) => !item.is_sticky);
    },

    _startPopupTimer(popup) {
        this._clearPopupTimer(popup.id);
        const seconds = popup.timeout || this.notifyState.defaultTimeout
            || STREAMS_NOTIFY_DEFAULT_TIMEOUT;
        this._popupTimers.set(
            popup.id,
            browser.setTimeout(() => this.closePopup(popup.id), seconds * 1000)
        );
    },

    _clearPopupTimer(notifyId) {
        const timer = this._popupTimers.get(notifyId);
        if (timer) {
            browser.clearTimeout(timer);
            this._popupTimers.delete(notifyId);
        }
    },

    /** @param {number} notifyId */
    closePopup(notifyId) {
        this._clearPopupTimer(notifyId);
        const index = this.notifyState.popups.findIndex((item) => item.id === notifyId);
        if (index === -1) {
            return;
        }
        this.notifyState.popups.splice(index, 1);
        const sticky = this.stickyPopups;
        if (this.notifyState.stickyIndex >= sticky.length) {
            this.notifyState.stickyIndex = Math.max(sticky.length - 1, 0);
        }
    },

    /**
     * Наведение мыши останавливает таймер (E4): попап не должен исчезать
     * из-под курсора, пока его читают.
     *
     * @param {number} notifyId
     */
    pausePopup(notifyId) {
        this._clearPopupTimer(notifyId);
    },

    /** @param {number} notifyId */
    resumePopup(notifyId) {
        const popup = this.notifyState.popups.find((item) => item.id === notifyId);
        if (popup && !popup.is_sticky) {
            this._startPopupTimer(popup);
        }
    },

    /** @param {number} index позиция в стеке sticky (E5) */
    showStickyPopup(index) {
        const sticky = this.stickyPopups;
        if (!sticky.length) {
            return;
        }
        this.notifyState.stickyIndex = Math.min(Math.max(index, 0), sticky.length - 1);
    },

    // ------------------------------------------------------------
    // ОТМЕТКА ПОКАЗА (E6)
    // ------------------------------------------------------------

    _queuePopupShown(notifyId) {
        if (!this._shownQueue.includes(notifyId)) {
            this._shownQueue.push(notifyId);
        }
        if (this._shownTimer) {
            browser.clearTimeout(this._shownTimer);
        }
        this._shownTimer = browser.setTimeout(
            () => this._flushPopupShown(),
            POPUP_SHOWN_DELAY
        );
    },

    async _flushPopupShown() {
        this._shownTimer = null;
        const notifyIds = this._shownQueue;
        this._shownQueue = [];
        if (!notifyIds.length) {
            return;
        }
        try {
            await this.env.services.orm.silent.call(
                "mail.notify",
                "streams_notify_popup_shown",
                [notifyIds]
            );
        } catch {
            // отметка показа — не критичный путь: не отметили, значит
            // попап всплывёт ещё раз при следующем логине
        }
    },

    // ------------------------------------------------------------
    // ЗВУК (E8, E9)
    // ------------------------------------------------------------

    /** @type {boolean} персональный Mute из `res.users.settings` (E9). */
    get isNotifySoundMuted() {
        return Boolean(this.store.settings?.is_streams_notify_sound_muted);
    },

    /**
     * Сигнал о новом уведомлении.
     *
     * Только в мастер-вкладке: три открытых вкладки не должны звонить
     * трижды. Ядро 19 определяет мастера сервисом `multi_tab`
     * (`isOnMainTab()` асинхронный), звук играет `mail.sound_effects`.
     */
    async playNotifySound() {
        if (this.isNotifySoundMuted) {
            return;
        }
        const multiTab = this.env.services.multi_tab;
        if (multiTab && !(await multiTab.isOnMainTab())) {
            return;
        }
        const soundEffects = this.env.services["mail.sound_effects"];
        if (soundEffects) {
            soundEffects.play(NOTIFY_SOUND);
            return;
        }
        this._playFallbackSound();
    },

    /** Фолбэк на случай, когда сервис звуков ещё не стартовал. */
    _playFallbackSound() {
        if (!browser.Audio) {
            return;
        }
        if (!this._fallbackAudio) {
            const audio = new browser.Audio();
            const extension = audio.canPlayType("audio/ogg; codecs=vorbis")
                ? ".ogg"
                : ".mp3";
            audio.src = NOTIFY_SOUND_URL + extension;
            this._fallbackAudio = audio;
        }
        this._fallbackAudio.currentTime = 0;
        Promise.resolve(this._fallbackAudio.play()).catch(() => {});
    },

    /**
     * Переключить персональный Mute (E9).
     *
     * Настройка живёт в `res.users.settings`; ядро 19 сериализует все
     * поля модели целиком, поэтому значение доезжает в `store.settings`
     * и на старте, и bus-пушем `res.users.settings` после записи —
     * второй вкладке ничего досылать не нужно.
     */
    async toggleNotifySoundMute() {
        const settings = this.store.settings;
        const muted = !this.isNotifySoundMuted;
        // оптимистично: тумблер должен отзываться мгновенно
        settings.is_streams_notify_sound_muted = muted;
        if (!settings.id) {
            return;
        }
        try {
            await this.env.services.orm.call(
                "res.users.settings",
                "set_res_users_settings",
                [[settings.id]],
                { new_settings: { is_streams_notify_sound_muted: muted } }
            );
        } catch (error) {
            settings.is_streams_notify_sound_muted = !muted;
            throw error;
        }
    },

    // ------------------------------------------------------------
    // ПРОЧИТАННОСТЬ И ПЕРЕХОДЫ
    // ------------------------------------------------------------

    /**
     * Отметить уведомления прочитанными (§12.5).
     *
     * @param {number[]} notifyIds
     * @returns {Promise<{counter: number}>}
     */
    async markNotifyRead(notifyIds) {
        if (!notifyIds?.length) {
            return { counter: this.notifyState.counter };
        }
        const result = await this.env.services.orm.silent.call(
            "mail.notify",
            "streams_notify_mark_read",
            [notifyIds]
        );
        this.notifyState.counter = result?.counter ?? 0;
        this._syncNotifyChannelCounter();
        for (const notifyId of notifyIds) {
            const record = this.store["mail.notify"].get(notifyId);
            if (record && !record.read_date) {
                // точное время придёт с сервера при следующей загрузке
                // ленты; здесь важен только факт «уже прочитано»
                record.read_date = serializeDateTime(DateTime.now());
            }
        }
        return result;
    },

    /**
     * Открыть личный канал Notifications, создав его при первом заходе.
     *
     * Канал заводится лениво, поэтому в момент клика клиент может о нём
     * ещё не знать. Серверный `streams_notify_open_channel` отдаёт
     * `{channel_id, data}`, где `data` — Store-payload канала вместе с
     * записью `discuss.channel.member` текущего пользователя: из неё
     * клиент вычисляет `is_pinned` (нет `unpin_dt`) → `displayToSelf` →
     * `displayInSidebar`, и канал появляется в сайдбаре сам (S3).
     */
    async openNotifyChannel() {
        const result = await this.env.services.orm.call(
            "mail.notify",
            "streams_notify_open_channel",
            []
        );
        if (!result?.channel_id) {
            return;
        }
        this.notifyState.channelId = result.channel_id;
        if (result.data) {
            this.store.insert(result.data);
        }
        const thread = this.store.Thread.get({
            model: "discuss.channel",
            id: result.channel_id,
        });
        if (thread && this.store.discuss?.isActive) {
            thread.setAsDiscussThread();
            return;
        }
        await this.env.services.action.doAction({
            type: "ir.actions.client",
            tag: "mail.action_discuss",
            context: { active_id: `discuss.channel_${result.channel_id}` },
        });
    },

    /**
     * Открыть форму записи-источника уведомления (E12).
     *
     * @param {string} resModel
     * @param {number} resId
     */
    openNotifyRecord(resModel, resId) {
        if (!resModel || !resId) {
            return;
        }
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
        });
    },

    // ------------------------------------------------------------
    // КОМПОЗЕР (§12.2, Р5)
    // ------------------------------------------------------------

    /**
     * Открыть диалог отправки уведомления.
     *
     * Точка входа для кнопки Notify чаттера и шапки канала (WP2), а
     * также для кнопки «New notification» в ленте (F10 — без записи).
     *
     * @param {Object} [options]
     * @param {string} [options.resModel] модель записи-источника
     * @param {number} [options.resId] id записи-источника
     * @param {string} [options.recordName] имя записи для подписи
     */
    openNotifyComposer({ resModel, resId, recordName } = {}) {
        this.env.services.dialog.add(StreamsNotifyComposer, {
            resModel: resModel || false,
            resId: resId || false,
            recordName: recordName || "",
        });
    },

    /**
     * Ответить на уведомление (§12.6, E13).
     *
     * Получателя выбирать не дают: ответ уходит только автору родителя,
     * это форсирует сам сервер (`streams_notify_reply`). Sticky и
     * таймаут наследуются от родителя.
     *
     * @param {number} notifyId
     */
    replyToNotify(notifyId) {
        const source =
            this.notifyState.popups.find((item) => item.id === notifyId) ||
            this.store["mail.notify"].get(notifyId);
        if (!source) {
            return;
        }
        this.env.services.dialog.add(StreamsNotifyComposer, {
            parentId: notifyId,
            parentAuthorName: source.author?.name || "",
            isSticky: Boolean(source.is_sticky),
            timeout: source.timeout || this.notifyState.defaultTimeout,
        });
    },
});
