import { fields, Record } from "@mail/core/common/record";

/**
 * Уведомление (§12) на клиенте.
 *
 * Форма записи повторяет серверный `mail.notify._streams_payload`
 * (`models/mail_notify.py`) — он же payload шины `streams.notify/new` и
 * `streams.notify/update`, он же элемент лент Received/Sent. Держать одну
 * модель на все три источника дешевле, чем три разных разбора.
 *
 * Осторожно с типами: `bus_service.subscribe` отдаёт глубокую JSON-копию
 * payload'а, поэтому по шине приезжают только строки и числа. Тело
 * санитизировано сервером и оборачивается в markup уже здесь — это и
 * делает `fields.Html`.
 */
export class StreamsNotify extends Record {
    static _name = "mail.notify";
    static id = "id";

    /** @type {number} */
    id;
    /** @type {string} Тело уведомления (санитизировано сервером). */
    body = fields.Html("");
    /** Момент создания; сервер шлёт его под ключом `date`, не `create_date`. */
    date = fields.Datetime();
    /**
     * Автор плоским словарём `{id, name}`.
     *
     * Не `fields.One("res.partner")`: `id` здесь — идентификатор
     * `res.users` (`mail.notify.author_id`), а не партнёра. Реляционное
     * поле заставило бы Store завести `res.partner` с чужим id и
     * переписать имя постороннему контакту (сайдбар, чаты, чаттер брали
     * бы его из Store). Записью партнёра автор уведомления нигде и не
     * нужен: и карточка, и лента читают только `author.name`.
     *
     * @type {{id: number, name: string}|false}
     */
    author = fields.Attr(false);
    /** @type {boolean} */
    is_sticky = fields.Attr(false);
    /** @type {number} Автозакрытие не-sticky попапа, сек (сервер жмёт в 3..300). */
    timeout = fields.Attr(0);
    /** @type {string|false} */
    res_model = fields.Attr(false);
    /** @type {number|false} */
    res_id = fields.Attr(false);
    /** @type {string} */
    record_name = fields.Attr("");
    /**
     * Вложения плоскими словарями `{id, name, mimetype, size}`.
     *
     * Не `fields.Many("ir.attachment")`: серверный payload не Store-образный
     * (`size` вместо `file_size`, нет токенов доступа), а скачиваются они
     * по прямой ссылке `/web/content/<id>?download=true`.
     *
     * @type {Object[]}
     */
    attachments = fields.Attr([]);
    /** @type {{id: number, mimetype: string, duration: number}|false} */
    voice = fields.Attr(false);
    /** @type {string|false} */
    transcript = fields.Attr(false);
    /** @type {string|false} Статус расшифровки голоса («Transcribing…»). */
    transcript_state = fields.Attr(false);
    /** @type {number|false} Родитель для Reply (голый id). */
    parent_id = fields.Attr(false);
    /** @type {string|false} Когда прочитано мной; есть только во вкладке Received. */
    read_date = fields.Attr(false);
    /** @type {boolean} Попап уже показывали — при следующем логине не всплывёт. */
    popup_shown = fields.Attr(false);
    /**
     * Получатели с их `read_date`; приезжает только для вкладки Sent
     * (`with_recipients=True`).
     *
     * @type {Object[]}
     */
    recipients = fields.Attr([]);
}

StreamsNotify.register();
