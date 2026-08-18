/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";

import {
    VoiceRecorder,
    isVoiceRecordingSupported,
} from "@streams/js/voice_recorder";

const { useState } = owl.hooks;

const SEARCH_DELAY = 300;
const DEFAULT_TIMEOUT = 10;

/**
 * Форма отправки уведомления (§12.2).
 *
 * Диалог, а не композер чаттера: уведомление живёт вне `mail.message`, у
 * него свои получатели, свои настройки попапа и единственная в продукте
 * запись голоса (§12.3).
 */
export class StreamsNotifyComposer extends Dialog {

    setup() {
        super.setup();
        this.rpc = useService('rpc');
        this.notification = useService('notification');
        this.state = useState({
            recipients: [],
            query: '',
            results: [],
            body: '',
            isSticky: Boolean(this.props.isSticky),
            timeout: this.props.timeout
                || (this.props.service && this.props.service.state.defaultTimeout)
                || DEFAULT_TIMEOUT,
            attachments: [],
            voice: false,
            isRecording: false,
            recordDuration: 0,
            isSending: false,
            error: '',
        });
        this.canRecord = isVoiceRecordingSupported();
        this._searchTimer = undefined;
        this._recorder = undefined;
        this.title = this.props.parentId
            ? this.env._t("Reply") : this.env._t("Notify");
        if (this.props.parentId && this.props.parentAuthor) {
            // ответ уходит только автору исходного — получателя не выбирают
            this.state.recipients = [
                { id: 0, name: this.props.parentAuthor },
            ];
        }
    }

    willUnmount() {
        if (this._recorder) {
            this._recorder.release();
        }
        if (this._searchTimer) {
            browser.clearTimeout(this._searchTimer);
        }
    }

    //----------------------------------------------------------------------
    // Признаки формы
    //----------------------------------------------------------------------

    get isReply() {
        return Boolean(this.props.parentId);
    }

    /**
     * Голос делает уведомление sticky принудительно (§12.3): попап не
     * должен закрыться раньше, чем дослушают запись.
     */
    get isStickyForced() {
        return Boolean(this.state.voice);
    }

    get isSendDisabled() {
        if (this.state.isSending || this.state.isRecording) {
            return true;
        }
        if (!this.isReply && !this.state.recipients.length) {
            return true;
        }
        return !this.state.body.trim() && !this.state.voice
            && !this.state.attachments.length;
    }

    formatDuration(seconds) {
        const total = Math.max(parseInt(seconds || 0, 10), 0);
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return minutes + ':' + (rest < 10 ? '0' : '') + rest;
    }

    voiceUrl(attachmentId) {
        return '/web/content/' + attachmentId;
    }

    //----------------------------------------------------------------------
    // Получатели
    //----------------------------------------------------------------------

    onInputRecipient(ev) {
        this.state.query = ev.target.value;
        if (this._searchTimer) {
            browser.clearTimeout(this._searchTimer);
        }
        this._searchTimer = browser.setTimeout(
            () => this._searchRecipients(), SEARCH_DELAY);
    }

    async _searchRecipients() {
        const query = this.state.query.trim();
        if (!query) {
            this.state.results = [];
            return;
        }
        const selected = this.state.recipients.map(user => user.id);
        const results = await this.rpc(
            '/web/dataset/call_kw/res.users/name_search', {
                model: 'res.users',
                method: 'name_search',
                args: [],
                kwargs: {
                    name: query,
                    args: [
                        ['share', '=', false],
                        ['active', '=', true],
                        ['id', 'not in', selected],
                    ],
                    limit: 8,
                },
            });
        this.state.results = (results || []).map(
            ([id, name]) => ({ id, name }));
    }

    onClickResult(ev) {
        const id = parseInt(ev.currentTarget.dataset.userId, 10);
        const found = this.state.results.find(user => user.id === id);
        if (found) {
            this.state.recipients.push(found);
        }
        this.state.results = [];
        this.state.query = '';
    }

    onClickRemoveRecipient(ev) {
        const id = parseInt(ev.currentTarget.dataset.userId, 10);
        this.state.recipients = this.state.recipients.filter(
            user => user.id !== id);
    }

    //----------------------------------------------------------------------
    // Поля формы
    //----------------------------------------------------------------------

    onInputBody(ev) {
        this.state.body = ev.target.value;
    }

    onChangeSticky(ev) {
        this.state.isSticky = ev.target.checked;
    }

    onChangeTimeout(ev) {
        this.state.timeout = parseInt(ev.target.value, 10) || DEFAULT_TIMEOUT;
    }

    //----------------------------------------------------------------------
    // Вложения
    //----------------------------------------------------------------------

    async onChangeFiles(ev) {
        const files = Array.from(ev.target.files || []);
        for (const file of files) {
            const uploaded = await this._upload(file, file.name);
            if (uploaded) {
                this.state.attachments.push({
                    id: uploaded.id,
                    name: uploaded.name || file.name,
                });
            }
        }
        ev.target.value = '';
    }

    onClickRemoveAttachment(ev) {
        const id = parseInt(ev.currentTarget.dataset.attachmentId, 10);
        this.state.attachments = this.state.attachments.filter(
            attachment => attachment.id !== id);
    }

    /**
     * Загрузка штатным маршрутом ядра: своего контроллера не заводим,
     * `/mail/attachment/upload` проверяет членство только для каналов.
     *
     * @private
     */
    async _upload(file, fileName) {
        const formData = new FormData();
        formData.append('csrf_token', odoo.csrf_token);
        formData.append('is_pending', 'true');
        formData.append('thread_id', '0');
        formData.append('thread_model', 'mail.notify');
        formData.append('ufile', file, fileName);
        const response = await browser.fetch('/mail/attachment/upload', {
            method: 'POST',
            body: formData,
        });
        const result = await response.json();
        if (!result || result.error) {
            this.state.error = (result && result.error)
                || this.env._t("The file could not be uploaded.");
            return undefined;
        }
        return result;
    }

    //----------------------------------------------------------------------
    // Голос (§12.3)
    //----------------------------------------------------------------------

    async onClickRecord() {
        this.state.error = '';
        this._recorder = new VoiceRecorder({
            onTick: seconds => {
                this.state.recordDuration = seconds;
            },
            onStop: (blob, seconds, mimeType) => this._onRecordStop(
                blob, seconds, mimeType),
        });
        try {
            await this._recorder.start();
        } catch (_error) {
            this._recorder = undefined;
            this.state.error = this.env._t(
                "Microphone access was denied. Allow it in the browser to " +
                "record a voice message.");
            return;
        }
        this.state.isRecording = true;
        this.state.recordDuration = 0;
    }

    onClickStopRecord() {
        if (this._recorder) {
            this._recorder.stop();
        }
        this.state.isRecording = false;
    }

    async _onRecordStop(blob, seconds, mimeType) {
        this.state.isRecording = false;
        if (!blob || !blob.size) {
            return;
        }
        const fileName = VoiceRecorder.buildFileName(mimeType);
        const uploaded = await this._upload(blob, fileName);
        if (!uploaded) {
            return;
        }
        this.state.voice = {
            id: uploaded.id,
            name: uploaded.name || fileName,
            duration: seconds,
        };
        // голос всегда sticky — переключатель заблокирован в шаблоне
        this.state.isSticky = true;
    }

    onClickRemoveVoice() {
        this.state.voice = false;
    }

    //----------------------------------------------------------------------
    // Отправка
    //----------------------------------------------------------------------

    async onClickSend() {
        if (this.isSendDisabled) {
            return;
        }
        this.state.isSending = true;
        this.state.error = '';
        const values = {
            body: this.state.body,
            attachment_ids: this.state.attachments.map(
                attachment => attachment.id),
            is_sticky: this.state.isSticky,
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
                await this.rpc(
                    '/web/dataset/call_kw/mail.notify/streams_notify_reply', {
                        model: 'mail.notify',
                        method: 'streams_notify_reply',
                        args: [this.props.parentId, values],
                        kwargs: {},
                    });
            } else {
                values.user_ids = this.state.recipients.map(user => user.id);
                await this.rpc(
                    '/web/dataset/call_kw/mail.notify/streams_notify_send', {
                        model: 'mail.notify',
                        method: 'streams_notify_send',
                        args: [values],
                        kwargs: {},
                    });
            }
        } catch (error) {
            this.state.isSending = false;
            throw error;
        }
        this.notification.add(this.env._t("Notification sent."),
            { type: 'success' });
        this.close();
    }
}

StreamsNotifyComposer.template = 'web.Dialog';
StreamsNotifyComposer.bodyTemplate = 'streams.NotifyComposerBody';
StreamsNotifyComposer.footerTemplate = 'streams.NotifyComposerFooter';
StreamsNotifyComposer.title = 'Notify';
StreamsNotifyComposer.size = 'modal-md';
