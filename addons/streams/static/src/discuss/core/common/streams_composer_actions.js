import { streamsSendMessageAction } from "@streams/core/common/streams_actions";

import { registerComposerAction } from "@mail/core/common/composer_actions";

import { _t } from "@web/core/l10n/translation";

/**
 * Композер канала записи (§11.2, разрывы C3/C4).
 *
 * В клиенте 15 из канала можно было отправить только комментарий; здесь
 * добавлены переключатель Comment/Note и кнопка внешнего сообщения.
 * Сервер к этому готов: `discuss.channel.message_post` модуля прокидывает
 * kwargs (в том числе `subtype_xmlid`) на запись-источник, а
 * `/mail/message/post` пропускает `subtype_xmlid` в разрешённых
 * параметрах (`mail_thread._get_allowed_message_params`).
 *
 * @param {{composer: import("models").Composer}} params
 */
function isStreamsRecordComposer({ composer }) {
    // при редактировании сообщения (`composer.message`) переключать поток
    // нельзя: подтип уже проставлен на существующем сообщении
    return composer?.targetThread?.channel_kind === "record" && !composer.message;
}

registerComposerAction("streams-comment", {
    condition: isStreamsRecordComposer,
    icon: "fa fa-comment-o",
    inlineName: _t("Comment"),
    isActive: ({ composer }) => !composer.streamsIsNote,
    name: _t("Post an internal comment"),
    onSelected: ({ composer }) => (composer.streamsIsNote = false),
    sequenceQuick: 5,
});

registerComposerAction("streams-note", {
    condition: isStreamsRecordComposer,
    icon: "fa fa-sticky-note-o",
    inlineName: _t("Note"),
    isActive: ({ composer }) => Boolean(composer.streamsIsNote),
    name: _t("Log an internal note"),
    onSelected: ({ composer }) => (composer.streamsIsNote = true),
    sequenceQuick: 6,
});

registerComposerAction("streams-send-message", {
    condition: (params) => {
        const thread = params.composer?.targetThread;
        return isStreamsRecordComposer(params) && thread.res_model && thread.res_id;
    },
    icon: "fa fa-envelope-o",
    name: _t("Send Message"),
    /**
     * Внешняя переписка из канала (C4): тот же полный композер, что и по
     * кнопке чаттера, но по записи-источнику канала.
     */
    onSelected: async ({ composer, owner }) => {
        const thread = composer.targetThread;
        await owner.env.services.action.doAction(
            streamsSendMessageAction(thread.res_model, thread.res_id),
            {
                // сообщение уходит мимо клиентского Store; в канал оно
                // попадает проекцией на сервере — нужна перечитка
                onClose: () => thread.fetchNewMessages(),
            }
        );
    },
    sequence: 25,
});
