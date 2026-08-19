import { fields } from "@mail/core/common/record";
import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        /**
         * Поток сообщения (§2 ТЗ). `undefined` — «прочее»: системное
         * сообщение, не принадлежащее ни одному потоку; такие показываются
         * при любых фильтрах.
         *
         * @type {"note"|"comment"|"message"|"change"|"activity"|undefined}
         */
        this.streams_kind = fields.Attr(undefined);
        /**
         * Каналы, в которые спроецировано сообщение.
         *
         * Сервер отдаёт голые id (`models/mail_message.py`,
         * `_to_store_defaults`), поэтому это Attr, а не `fields.Many("Thread")`:
         * `Many` ждёт объекты или `{id}`, а идентификатор треда в 19 —
         * составной (`AND("model", "id")`), одного числа ему мало.
         *
         * @type {number[]}
         */
        this.stream_channel_ids = fields.Attr([]);
    },

    /** Сообщение об изменении полей (§8): рендерится трекингом ядра. */
    get isStreamsChange() {
        return this.streams_kind === "change";
    },
});
