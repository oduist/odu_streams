import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

/**
 * Дефолты фильтров отображения потоков (§6 ТЗ).
 *
 * Дубль серверных `STREAMS_FILTER_DEFAULTS` (`models/mail_message.py`):
 * тумблеры надо уметь нарисовать до того, как приедет `streams_filters`
 * канала, а на чаттерных тредах этого ключа не бывает вовсе.
 */
export const STREAMS_FILTER_DEFAULTS = {
    activity: true,
    change: false,
    comment: true,
    message: true,
    note: true,
};

/** Порядок тумблеров в шапке канала записи (как в клиенте 15). */
export const STREAMS_FILTER_ORDER = ["comment", "note", "message", "change", "activity"];

patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        /**
         * Вид канала: запись, личная лента изменений или уведомлений.
         * На тредах чаттера (`model !== "discuss.channel"`) всегда false.
         *
         * @type {"record"|"changes"|"notifications"|false}
         */
        this.channel_kind = fields.Attr(false);
        /**
         * Модель и id записи-источника канала записи.
         *
         * Осторожно: `res_model` — это НЕ ядровый `model`. У канала записи
         * `model === "discuss.channel"`, а `res_model` — модель документа,
         * который канал зеркалит.
         *
         * @type {string|false}
         */
        this.res_model = fields.Attr(false);
        /** @type {number|false} */
        this.res_id = fields.Attr(false);
        /**
         * Персональные фильтры участника; сервер отдаёт их только тому,
         * от чьего лица собран Store.
         *
         * @type {Object<string, boolean>}
         */
        this.streams_filters = fields.Attr({ ...STREAMS_FILTER_DEFAULTS });
    },

    /** Канал записи — единственный вид, где есть шапка с фильтрами. */
    get isStreamsRecordChannel() {
        return this.channel_kind === "record";
    },

    /**
     * Переключить фильтры потоков и перечитать ленту.
     *
     * Решение Р1 фазы 8: фильтрация серверная (`_message_fetch` уважает
     * `streams_filters` участника), поэтому одного оптимистичного
     * апдейта мало — после сохранения лента перечитывается целиком.
     *
     * @param {Object<string, boolean>} filters только меняемые потоки
     */
    async streamsSetFilters(filters) {
        const previous = this.streams_filters;
        // оптимистично: тумблер должен отзываться мгновенно
        this.streams_filters = { ...previous, ...filters };
        let stored;
        try {
            stored = await this.store.env.services.orm.call(
                "discuss.channel",
                "streams_set_filters",
                [[this.id]],
                { filters }
            );
        } catch (error) {
            this.streams_filters = previous;
            throw error;
        }
        if (stored) {
            // сервер — источник истины: он игнорирует незнакомые ключи
            this.streams_filters = { ...STREAMS_FILTER_DEFAULTS, ...stored };
        }
        await this.streamsReloadMessages();
    },

    /**
     * Сбросить кэш сообщений треда и перечитать свежую страницу.
     *
     * `fetchNewMessages()` здесь не годится: для `discuss.channel` он
     * выходит сразу, если тред уже загружен (`isLoaded`), и «догружает»
     * только сообщения новее последнего — то есть старую (уже
     * отфильтрованную сервером) страницу не перечитает.
     *
     * `loadAround()` без аргумента делает ровно нужное: сбрасывает
     * `isLoaded`, перекладывает текущие сообщения в `phantomMessages`
     * (лента не мигает пустотой), заново тянет последнюю страницу и
     * пересчитывает `loadOlder`/`loadNewer`
     * (`mail/static/src/core/common/thread_model.js`, `loadAround`).
     */
    async streamsReloadMessages() {
        await this.loadAround();
    },
});
