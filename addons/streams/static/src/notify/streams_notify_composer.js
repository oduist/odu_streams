import { Component, useState } from "@odoo/owl";

import { browser } from "@web/core/browser/browser";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

import { useVoiceRecorder } from "@mail/discuss/voice_message/common/voice_recorder";

/** Дебаунс поиска получателей (F1). */
const SEARCH_DELAY = 300;

/** Сколько имён показывать в подсказке (F1). */
const SEARCH_LIMIT = 8;

/** Границы таймаута попапа; те же зажимает сервер (F7). */
const MIN_TIMEOUT = 3;
const MAX_TIMEOUT = 300;

/**
 * Носитель вложений композера уведомления.
 *
 * Ядровый `useAttachmentUploader` здесь не годится дважды: он требует
 * Store-запись `Thread` (уведомление тредом не является) и стреляет в
 * `/mail/attachment/upload`, который в 19 сначала резолвит тред и без
 * него отвечает 404 (разрыв G4). Наружу выставлен ровно тот интерфейс,
 * которого ждёт ядровый `useVoiceRecorder`: `uploadFile(file, options)`.
 */
class StreamsNotifyUploader {
    /** @param {StreamsNotifyComposer} composer */
    constructor(composer) {
        this.composer = composer;
    }

    /**
     * @param {File|Blob} file
     * @param {{voice?: boolean}} [options]
     * @returns {Promise<Object|undefined>} `{id, name, mimetype, size}`
     */
    async uploadFile(file, options = {}) {
        const state = this.composer.state;
        state.error = "";
        state.isUploading = true;
        let uploaded;
        try {
            uploaded = await this._post(file);
        } finally {
            state.isUploading = false;
        }
        if (!uploaded) {
            return undefined;
        }
        if (options.voice) {
            state.voice = {
                ...uploaded,
                duration: this.composer.recordedSeconds,
            };
            // голос всегда sticky (§12.3): попап не должен закрыться
            // раньше, чем дослушают запись — это форсирует и сервер
            state.isSticky = true;
        } else {
            state.attachments.push(uploaded);
        }
        return uploaded;
    }

    async _post(file) {
        const formData = new FormData();
        formData.append("csrf_token", odoo.csrf_token);
        formData.append("ufile", file, file.name || "file");
        let response;
        try {
            response = await browser.fetch("/streams/notify/attachment/upload", {
                method: "POST",
                body: formData,
            });
        } catch {
            this.composer.state.error = _t("The file could not be uploaded.");
            return undefined;
        }
        const result = await response.json().catch(() => undefined);
        if (!response.ok || !result?.id) {
            this.composer.state.error =
                result?.error || _t("The file could not be uploaded.");
            return undefined;
        }
        return result;
    }
}

/**
 * Форма отправки уведомления (§12.2, решение Р5).
 *
 * Свой OWL-диалог, а не форма `ir.ui.view` и не композер чаттера:
 * уведомление живёт вне `mail.message`, у него свои получатели, свои
 * настройки попапа и единственная в продукте запись голоса (§12.3).
 */
export class StreamsNotifyComposer extends Component {
    static components = { Dialog };
    static props = {
        close: Function,
        /** Запись-источник; для «New notification» их нет (F10). */
        resModel: { type: [String, Boolean], optional: true },
        resId: { type: [Number, Boolean], optional: true },
        recordName: { type: String, optional: true },
        /** Родитель ответа (§12.6); задаёт режим Reply. */
        parentId: { type: Number, optional: true },
        parentAuthorName: { type: String, optional: true },
        isSticky: { type: Boolean, optional: true },
        timeout: { type: Number, optional: true },
    };
    static template = "streams.NotifyComposer";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.streamsCore = useService("streams.core");
        this.state = useState({
            /** @type {{id: number, name: string}[]} */
            recipients: [],
            query: "",
            /** @type {{id: number, name: string}[]} */
            results: [],
            body: "",
            isSticky: Boolean(this.props.isSticky),
            timeout:
                this.props.timeout ||
                this.streamsCore.notifyState.defaultTimeout ||
                MIN_TIMEOUT,
            /** @type {Object[]} */
            attachments: [],
            /** @type {Object|false} */
            voice: false,
            isUploading: false,
            isSending: false,
            error: "",
        });
        // рекордер требует носителя вложений на компоненте — он читает
        // `this.attachmentUploader` в момент остановки записи
        this.attachmentUploader = new StreamsNotifyUploader(this);
        this.voiceRecorder = useVoiceRecorder();
        this.searchRecipients = useDebounced(
            () => this._searchRecipients(),
            SEARCH_DELAY
        );
    }

    // ------------------------------------------------------------
    // ПРИЗНАКИ ФОРМЫ
    // ------------------------------------------------------------

    get isReply() {
        return Boolean(this.props.parentId);
    }

    get title() {
        return this.isReply ? _t("Reply") : _t("Notify");
    }

    /** Голос делает уведомление sticky принудительно (F6). */
    get isStickyForced() {
        return Boolean(this.state.voice);
    }

    get isRecording() {
        return Boolean(this.voiceRecorder.recording);
    }

    get isSendDisabled() {
        if (this.state.isSending || this.state.isUploading || this.isRecording) {
            return true;
        }
        if (!this.isReply && !this.state.recipients.length) {
            return true;
        }
        return (
            !this.state.body.trim() &&
            !this.state.voice &&
            !this.state.attachments.length
        );
    }

    /**
     * Длительность последней записи в секундах.
     *
     * Ядровый рекордер отдаёт только форматированный `elapsed`
     * («01 : 23»); серверу нужно число, и оно же уезжает в payload.
     *
     * @type {number}
     */
    get recordedSeconds() {
        const [minutes, seconds] = String(this.voiceRecorder.elapsed || "")
            .split(":")
            .map((part) => parseInt(part.trim(), 10) || 0);
        return (minutes || 0) * 60 + (seconds || 0);
    }

    formatSize(bytes) {
        const kilobytes = Math.max(Math.round((bytes || 0) / 1024), 1);
        return `${kilobytes} kB`;
    }

    voiceUrl(attachmentId) {
        return `/web/content/${attachmentId}`;
    }

    // ------------------------------------------------------------
    // ПОЛУЧАТЕЛИ (F1, F2)
    // ------------------------------------------------------------

    onInputRecipient(ev) {
        this.state.query = ev.target.value;
        this.searchRecipients();
    }

    async _searchRecipients() {
        const query = this.state.query.trim();
        if (!query) {
            this.state.results = [];
            return;
        }
        const selected = this.state.recipients.map((user) => user.id);
        const results = await this.orm.silent.call("res.users", "name_search", [], {
            name: query,
            // `domain`, а не `args`: в 19 параметр переименован
            // (`name_search(name, domain, operator, limit)`) — приём
            // клиента 15 здесь молча упал бы с TypeError.
            //
            // Уведомления адресуются только внутренним и активным
            // (§12.2); то же сервер проверяет ещё раз при отправке.
            domain: [
                ["share", "=", false],
                ["active", "=", true],
                ["id", "not in", selected],
            ],
            limit: SEARCH_LIMIT,
        });
        this.state.results = (results || []).map(([id, name]) => ({ id, name }));
    }

    onClickResult(result) {
        if (!this.state.recipients.some((user) => user.id === result.id)) {
            this.state.recipients.push(result);
        }
        this.state.results = [];
        this.state.query = "";
    }

    onClickRemoveRecipient(recipient) {
        this.state.recipients = this.state.recipients.filter(
            (user) => user.id !== recipient.id
        );
    }

    // ------------------------------------------------------------
    // ПОЛЯ ФОРМЫ
    // ------------------------------------------------------------

    onInputBody(ev) {
        this.state.body = ev.target.value;
    }

    onChangeSticky(ev) {
        this.state.isSticky = ev.target.checked;
    }

    onChangeTimeout(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.timeout = Math.min(
            Math.max(value || this.streamsCore.notifyState.defaultTimeout, MIN_TIMEOUT),
            MAX_TIMEOUT
        );
    }

    // ------------------------------------------------------------
    // ВЛОЖЕНИЯ И ГОЛОС (F4, F5)
    // ------------------------------------------------------------

    async onChangeFiles(ev) {
        const files = [...(ev.target.files || [])];
        for (const file of files) {
            await this.attachmentUploader.uploadFile(file);
        }
        ev.target.value = "";
    }

    onClickRemoveAttachment(attachment) {
        this.state.attachments = this.state.attachments.filter(
            (item) => item.id !== attachment.id
        );
    }

    onClickRemoveVoice() {
        this.state.voice = false;
    }

    onClickRecord() {
        this.state.error = "";
        this.voiceRecorder.onClick();
    }

    // ------------------------------------------------------------
    // ОТПРАВКА (F9)
    // ------------------------------------------------------------

    async onClickSend() {
        if (this.isSendDisabled) {
            return;
        }
        this.state.isSending = true;
        this.state.error = "";
        const values = {
            body: this.state.body,
            attachment_ids: this.state.attachments.map((item) => item.id),
            is_sticky: this.state.isSticky || this.isStickyForced,
            timeout: this.state.timeout,
        };
        if (this.state.voice) {
            values.voice_attachment_id = this.state.voice.id;
            values.voice_duration = this.state.voice.duration;
        }
        if (this.props.resModel && this.props.resId) {
            values.res_model = this.props.resModel;
            values.res_id = this.props.resId;
        }
        try {
            if (this.isReply) {
                // получателя не передаём: сервер сам адресует ответ
                // автору родителя (F3)
                await this.orm.call("mail.notify", "streams_notify_reply", [
                    this.props.parentId,
                    values,
                ]);
            } else {
                values.user_ids = this.state.recipients.map((user) => user.id);
                await this.orm.call("mail.notify", "streams_notify_send", [values]);
            }
        } catch (error) {
            this.state.isSending = false;
            throw error;
        }
        this.notification.add(_t("Notification sent."), { type: "success" });
        this.props.close();
    }
}
