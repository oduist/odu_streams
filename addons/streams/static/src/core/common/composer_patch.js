import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { toRaw } from "@odoo/owl";

patch(Composer.prototype, {
    /**
     * Композер канала записи сейчас в режиме заметки (C3).
     *
     * Персистентный переключатель канала (`discuss/core/common/
     * streams_composer_actions.js`). В чаттере записи его нет: там режим
     * берётся из `props.type`, а заметка отправляется разовым флагом
     * `streamsNoteRequested` (кнопка Note футера, фаза 9.5).
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

    /**
     * Показывать ли кнопку Note рядом с ядровой Send (фаза 9.5).
     *
     * Только композер чаттера записи: `env.inChatter` ставит сам чаттер
     * (`childSubEnv`), поэтому каналы Discuss, окна чата и наш диалог
     * Notify сюда не попадают. Режим правки сообщения (`composer.message`)
     * исключён — там подтип уже проставлен, менять его нечем; режим
     * `note` (его включает ядровый message action «Reply») тоже: в нём
     * заметку шлёт сама Send.
     */
    get streamsShowsNoteButton() {
        return Boolean(
            this.env.inChatter &&
                !this.props.composer.message &&
                this.props.type === "message" &&
                this.thread &&
                this.thread.model !== "discuss.channel"
        );
    },

    /**
     * Отправить набранное заметкой (кнопка Note футера, фаза 9.5).
     *
     * Не режим, а вторая отправка: флаг живёт ровно на время вызова
     * `sendMessage` и нигде не сохраняется. Он транзиентный намеренно —
     * состояние «композер сейчас в заметках» пользователю не обещано, обе
     * кнопки доступны всегда и шлют один и тот же набранный текст.
     *
     * `postData` читается синхронно внутри `processMessage`, который
     * `sendMessage` дожидается, — к моменту `finally` подтип уже уехал в
     * запрос.
     */
    async streamsSendAsNote() {
        this.streamsNoteRequested = true;
        try {
            await this.sendMessage();
        } finally {
            this.streamsNoteRequested = false;
        }
    },

    get postData() {
        const postData = super.postData;
        if (this.streamsIsNote || this.streamsNoteRequested) {
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
