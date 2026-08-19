import { Component, markup } from "@odoo/owl";

import { deserializeDateTime } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";

const { DateTime } = luxon;

/**
 * Карточка уведомления: тело, голос, транскрипт, вложения (§12.4, §12.5).
 *
 * Одна и та же разметка в попапе и в ленте — как в клиенте 15, где эти
 * два шаблона расходились только обвязкой. Обвязку (крестик, Reply,
 * список получателей) владелец докладывает слотами.
 */
export class StreamsNotifyCard extends Component {
    static props = {
        /** Элемент `mail.notify._streams_payload`. */
        notify: Object,
        slots: { type: Object, optional: true },
    };
    static template = "streams.NotifyCard";

    setup() {
        this.streamsCore = useService("streams.core");
    }

    /**
     * Тело уведомления.
     *
     * Санитизацию делает сервер (`tools.plaintext2html` при создании,
     * поле `fields.Html`), поэтому здесь остаётся только снять
     * экранирование. Через шину тело приезжает обычной строкой — шина
     * отдаёт JSON-копию payload'а, markup по ней не переживает.
     */
    get body() {
        return markup(this.props.notify.body || "");
    }

    /** @type {boolean} расшифровка ещё считается (§12.3). */
    get isTranscribing() {
        return (
            !this.props.notify.transcript &&
            this.props.notify.transcript_state === "queued"
        );
    }

    /**
     * @param {string|false} value серверная дата-строка UTC
     * @param {Object} [options] см. luxon `toLocaleString`
     */
    formatDate(value, options) {
        if (!value) {
            return "";
        }
        return deserializeDateTime(value).toLocaleString(
            options || DateTime.TIME_SIMPLE
        );
    }

    /** @param {string|false} value */
    formatDateTime(value) {
        return this.formatDate(value, DateTime.DATETIME_MED);
    }

    /** @param {number} seconds */
    formatDuration(seconds) {
        const total = Math.max(parseInt(seconds || 0, 10), 0);
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return `${minutes}:${rest < 10 ? "0" : ""}${rest}`;
    }

    /** @param {number} attachmentId */
    attachmentUrl(attachmentId) {
        return `/web/content/${attachmentId}?download=true`;
    }

    /**
     * Ссылка на голос.
     *
     * Плеер — обычный `<audio controls>`, а не ядровый `VoicePlayer`:
     * тот принимает Store-запись `ir.attachment` и рисует волну, скачивая
     * и декодируя файл; серверный payload уведомления отдаёт вложения
     * плоскими словарями без токенов доступа. Доступ к `/web/content`
     * даёт `ir.attachment.check` по записи-владельцу (`mail.notify`).
     *
     * @param {number} attachmentId
     */
    voiceUrl(attachmentId) {
        return `/web/content/${attachmentId}`;
    }

    onClickRecord(ev) {
        ev.preventDefault();
        this.streamsCore.openNotifyRecord(
            this.props.notify.res_model,
            this.props.notify.res_id
        );
    }
}
