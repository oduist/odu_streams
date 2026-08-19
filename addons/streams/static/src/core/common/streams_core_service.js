import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

/** Типы шины, которые шлёт сервер streams (`models/mail_notify.py`, `mail_message.py`). */
export const STREAMS_BUS_NOTIFY_NEW = "streams.notify/new";
export const STREAMS_BUS_NOTIFY_UPDATE = "streams.notify/update";
export const STREAMS_BUS_NOTIFY_COUNTER = "streams.notify/counter";
export const STREAMS_BUS_CHANGES_UPDATED = "streams.changes/updated";

/** Дефолт таймаута попапа до приезда серверного `streams_notify` (§14). */
export const STREAMS_NOTIFY_DEFAULT_TIMEOUT = 10;

/**
 * Единая точка приёма пушей streams — по образцу ядровых `mail.core.common`
 * и `discuss.core.common`.
 *
 * Зачем отдельный сервис, а не подписка в компонентах: уведомление должно
 * долетать и тогда, когда ни лента, ни колокол не смонтированы (§12.4), —
 * иначе попапы теряются между переходами.
 *
 * Пока пакет WP3 (подсистема Notify) не приехал, сервис сам держит
 * состояние `notifyState` и наполняет его. WP3 наращивает поведение, не
 * трогая подписки: у каждого типа шины свой метод-обработчик, который
 * можно пропатчить (`patch(StreamsCore.prototype, ...)`), а сверх того
 * каждый пуш ретранслируется в `env.bus` — на него можно подписаться
 * хуком `useBus` из любого компонента.
 */
export class StreamsCore {
    constructor(env, services) {
        this.env = env;
        this.busService = services.bus_service;
        this.store = services["mail.store"];
        /**
         * Состояние подсистемы уведомлений.
         *
         * @type {{counter: number, channelId: number|false,
         *         defaultTimeout: number, pending: Object[]}}
         */
        this.notifyState = reactive({
            // бейдж колокола
            counter: 0,
            // личный канал Notifications; false — ещё не создан
            channelId: false,
            defaultTimeout: STREAMS_NOTIFY_DEFAULT_TIMEOUT,
            // уведомления, попап по которым ещё не показывали
            pending: [],
        });
    }

    setup() {
        this.busService.subscribe(STREAMS_BUS_NOTIFY_NEW, (payload) =>
            this.onNotifyNew(payload)
        );
        this.busService.subscribe(STREAMS_BUS_NOTIFY_UPDATE, (payload) =>
            this.onNotifyUpdate(payload)
        );
        this.busService.subscribe(STREAMS_BUS_NOTIFY_COUNTER, (payload) =>
            this.onNotifyCounter(payload)
        );
        this.busService.subscribe(STREAMS_BUS_CHANGES_UPDATED, (payload) =>
            this.onChangesUpdated(payload)
        );
        // глобальное значение Store могло приехать раньше старта сервиса
        this.applyInitPayload(this.store.streams_notify);
    }

    /**
     * Стартовый payload из `res.users._init_messaging` (E1).
     *
     * Приходит глобальным значением Store `streams_notify`
     * (`models/res_users.py` → `models/mail_notify.py:_streams_init_messaging`).
     *
     * @param {{counter: number, channel_id: number|false,
     *          default_timeout: number, pending: Object[]}} [payload]
     */
    applyInitPayload(payload) {
        if (!payload) {
            return;
        }
        this.notifyState.counter = payload.counter ?? 0;
        this.notifyState.channelId = payload.channel_id ?? false;
        this.notifyState.defaultTimeout =
            payload.default_timeout || STREAMS_NOTIFY_DEFAULT_TIMEOUT;
        for (const notifyData of payload.pending ?? []) {
            this._insertNotify(notifyData);
        }
    }

    /** Новое уведомление: payload — элемент ленты плюс `counter`. */
    onNotifyNew(payload) {
        const { counter, ...notifyData } = payload;
        this._insertNotify(notifyData);
        if (counter !== undefined) {
            this.notifyState.counter = counter;
        }
        this.env.bus.trigger(STREAMS_BUS_NOTIFY_NEW, payload);
    }

    /**
     * Точечная правка уведомления: расшифровка голоса либо `read_date`
     * конкретного получателя.
     */
    onNotifyUpdate(payload) {
        if (payload?.id) {
            const notifyData = { ...payload };
            // `recipient` — отметка прочтения конкретного получателя для
            // вкладки Sent; полем модели она не является, её разбирает лента
            delete notifyData.recipient;
            this.store["mail.notify"].insert(notifyData);
        }
        this.env.bus.trigger(STREAMS_BUS_NOTIFY_UPDATE, payload);
    }

    onNotifyCounter(payload) {
        this.notifyState.counter = payload?.counter ?? 0;
        this.env.bus.trigger(STREAMS_BUS_NOTIFY_COUNTER, payload);
    }

    /**
     * Лента личного канала Changes изменилась.
     *
     * Тела в payload нет намеренно (`{id: <channel_id>}`): подписчик мог
     * потерять доступ к записи (§8.4), поэтому лента перезапрашивается —
     * права она уже учитывает. Ретрансляция в `env.bus` нужна пакету WP4:
     * подписка на `bus_service` из компонента ленты стоила бы отдельного
     * отписывания на размонтировании.
     */
    onChangesUpdated(payload) {
        this.env.bus.trigger(STREAMS_BUS_CHANGES_UPDATED, payload);
    }

    /**
     * Положить уведомление в Store и в очередь непоказанных попапов.
     *
     * @param {Object} notifyData элемент `_streams_payload`
     */
    _insertNotify(notifyData) {
        if (!notifyData?.id) {
            return;
        }
        this.store["mail.notify"].insert(notifyData);
        const known = this.notifyState.pending.findIndex(
            (item) => item.id === notifyData.id
        );
        if (known === -1) {
            this.notifyState.pending.push(notifyData);
        } else {
            this.notifyState.pending[known] = notifyData;
        }
    }
}

export const streamsCoreService = {
    dependencies: ["bus_service", "mail.store"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const streamsCore = reactive(new StreamsCore(env, services));
        streamsCore.setup();
        return streamsCore;
    },
};

registry.category("services").add("streams.core", streamsCoreService);
