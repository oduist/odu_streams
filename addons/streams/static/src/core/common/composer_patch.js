import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { toRaw } from "@odoo/owl";

patch(Composer.prototype, {
    /**
     * Композер канала записи сейчас в режиме заметки (C3).
     *
     * У чаттера свой переключатель — ядровые кнопки Comment/Note, поэтому
     * там режим берётся из `props.type` и это поле не используется.
     */
    get streamsIsNote() {
        return Boolean(
            this.thread?.channel_kind === "record" && this.props.composer.streamsIsNote
        );
    },

    /**
     * Тред, для которого streams запрещает автоматическую рассылку
     * получателям (см. `store_service_patch.js`).
     */
    get streamsSuppressesRecipients() {
        const thread = toRaw(this.props.composer).thread;
        return Boolean(thread) && this.store.streamsSuppressesRecipients(thread);
    },

    get placeholder() {
        if (this.props.placeholder) {
            return super.placeholder;
        }
        if (this.thread && this.thread.model !== "discuss.channel" && this.props.type === "message") {
            // ядровое «Send a message to followers…» обещает рассылку,
            // которой у нашего Comment нет (§7)
            return _t("Post an internal comment…");
        }
        if (this.streamsIsNote) {
            return _t("Log an internal note…");
        }
        return super.placeholder;
    },

    get postData() {
        const postData = super.postData;
        if (this.streamsIsNote) {
            // `isNote` — единственная ручка выбора подтипа в ядре:
            // `Store.getMessagePostParams` превращает его в
            // `subtype_xmlid: 'mail.mt_note'`, а `discuss.channel.message_post`
            // модуля прокидывает подтип на запись-источник
            postData.isNote = true;
        }
        return postData;
    },

    /**
     * Отправка без ядровой валидации e-mail получателей.
     *
     * Ядро (`mail/static/src/core/common/composer.js`, `sendMessage`) при
     * `type !== 'note'` молча отказывается отправлять, если у любого
     * предложенного получателя нет валидного e-mail. Для записей streams
     * строка получателей скрыта, а сами получатели в `partner_ids` не
     * попадают, — значит починить адрес пользователю негде, и проверка
     * превращается в неисправимую блокировку композера.
     *
     * Остальная часть ядрового метода воспроизведена дословно.
     */
    async sendMessage() {
        const composer = toRaw(this.props.composer);
        if (composer.message || !this.streamsSuppressesRecipients) {
            return super.sendMessage(...arguments);
        }
        this.composerActions.activePicker?.close?.();
        await this.processMessage(async (value) => {
            await this._sendMessage(value, this.postData, this.extraData);
        });
    },
});
