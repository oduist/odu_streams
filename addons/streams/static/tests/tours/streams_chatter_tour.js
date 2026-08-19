import { registry } from "@web/core/registry";

/**
 * Чаттер записи (§11.1, редизайн топбара фазой 9.5): состав кнопок и обе
 * отправки из футера композера.
 *
 * Тур намеренно проходит весь путь до сообщения в ленте: Hoot проверяет
 * разметку на mock-сервере, а здесь важно, что реальный `message_post`
 * доходит до записи и её канала — и что подтип у Send и Note разный.
 */
registry.category("web_tour.tours").add("streams_chatter_tour", {
    steps: () => [
        { trigger: ".o-mail-Chatter-topbar" },
        // ядровые Comment/Note убраны: композер открыт всегда
        { trigger: ".o-mail-Chatter-topbar:not(:has(button.o-mail-Chatter-sendMessage))" },
        { trigger: ".o-mail-Chatter-topbar:not(:has(button.o-mail-Chatter-logNote))" },
        { trigger: "button.o-streams-Chatter-sendExternal:contains('Message')" },
        { trigger: "button.o-streams-Chatter-notify:contains('Notify')" },
        { trigger: "button.o-streams-Chatter-changes:contains('Changes')" },
        { trigger: "button.o-streams-Chatter-invite:contains('Invite')" },

        // композер на экране без единого клика, в режиме комментария
        { trigger: ".o-mail-Composer" },
        // над внутренним комментарием нет строки получателей (§7)
        { trigger: ".o-mail-Chatter-top:not(:has(.o-mail-RecipientsInput))" },
        { trigger: ".o-mail-Composer-input", run: "click" },
        { trigger: ".o-mail-Composer-input", run: "edit Internal comment from tour" },
        { trigger: ".o-mail-Composer button[aria-label='Send']:enabled", run: "click" },
        { trigger: ".o-mail-Message:contains('Internal comment from tour')" },

        // композер остался открытым и пустым: Send снова неактивна
        { trigger: ".o-mail-Composer button[aria-label='Send']:disabled" },

        { trigger: ".o-mail-Composer-input", run: "click" },
        { trigger: ".o-mail-Composer-input", run: "edit Internal note from tour" },
        { trigger: "button.o-streams-Composer-note:enabled", run: "click" },
        { trigger: ".o-mail-Message:contains('Internal note from tour')" },
        { trigger: ".o-mail-Composer button[aria-label='Send']:disabled" },
    ],
});
