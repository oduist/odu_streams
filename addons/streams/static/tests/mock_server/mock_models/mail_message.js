import { mailModels } from "@mail/../tests/mail_test_helpers";
import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";

/** Подтипы streams (`data/mail_message_subtype_data.xml`). */
const STREAMS_SUBTYPES = {
    "streams.mt_change": "change",
    "streams.mt_activity": "activity",
    "streams.mt_message": "message",
};

/**
 * Mock-модель сообщения: поток и каналы-проекции (§2, §6).
 *
 * Оба ключа сервер отдаёт вычисляемыми `Store.Attr`
 * (`models/mail_message.py`, `_to_store_defaults`), а не полями чтения,
 * поэтому в mock-сервере они тоже добавляются в `_to_store_defaults`.
 */
export class MailMessage extends mailModels.MailMessage {
    get _to_store_defaults() {
        return [
            ...super._to_store_defaults,
            mailDataHelpers.Store.attr(
                "stream_channel_ids",
                (message) => message.stream_channel_ids || []
            ),
            mailDataHelpers.Store.attr("streams_kind", (message) =>
                this._streams_classify(message)
            ),
        ];
    }

    /**
     * Поток сообщения по подтипу и типу (упрощённый
     * `mail.message._streams_classify_vals`).
     *
     * Порядок проверок повторяет серверный: письмо — всегда внешняя
     * переписка, системный автолог без нашего подтипа — «прочее».
     *
     * @param {Object} message
     * @returns {string|false}
     */
    _streams_classify(message) {
        /** @type {import("mock_models").MailMessageSubtype} */
        const MailMessageSubtype = this.env["mail.message.subtype"];

        if (message.message_type === "user_notification") {
            return false;
        }
        if (["email", "email_outgoing"].includes(message.message_type)) {
            return "message";
        }
        const [subtype] = message.subtype_id
            ? MailMessageSubtype.browse(message.subtype_id)
            : [];
        const xmlid = subtype?.subtype_xmlid;
        if (xmlid && STREAMS_SUBTYPES[xmlid]) {
            return STREAMS_SUBTYPES[xmlid];
        }
        if (message.message_type === "notification") {
            return false;
        }
        if (xmlid === "mail.mt_note") {
            return "note";
        }
        if (xmlid === "mail.mt_comment") {
            return "comment";
        }
        return false;
    }
}
