import { registry } from "@web/core/registry";

/**
 * Чаттер записи (§11.1): состав кнопок и оба внутренних потока.
 *
 * Тур намеренно проходит весь путь до сообщения в ленте: Hoot проверяет
 * разметку на mock-сервере, а здесь важно, что реальный `message_post`
 * доходит до записи и её канала.
 */
registry.category("web_tour.tours").add("streams_chatter_tour", {
    steps: () => [
        { trigger: ".o-mail-Chatter-topbar" },
        // ядровые кнопки переименованы (B1/B2), классы ядра сохранены
        { trigger: "button.o-mail-Chatter-sendMessage:contains('Comment')" },
        { trigger: "button.o-mail-Chatter-logNote:contains('Note')" },
        { trigger: "button.o-streams-Chatter-sendExternal:contains('Send Message')" },
        { trigger: "button.o-streams-Chatter-notify:contains('Notify')" },
        { trigger: "button.o-streams-Chatter-changes:contains('Changes')" },
        { trigger: "button.o-streams-Chatter-invite:contains('Invite customer')" },

        { trigger: "button.o-mail-Chatter-sendMessage", run: "click" },
        // над внутренним комментарием нет строки получателей (§7)
        { trigger: ".o-mail-Chatter-top:not(:has(.o-mail-RecipientsInput))" },
        { trigger: ".o-mail-Composer-input", run: "edit Internal comment from tour" },
        { trigger: ".o-mail-Composer button[aria-label='Send']:enabled", run: "click" },
        { trigger: ".o-mail-Message:contains('Internal comment from tour')" },

        { trigger: "button.o-mail-Chatter-logNote", run: "click" },
        { trigger: ".o-mail-Composer-input", run: "edit Internal note from tour" },
        { trigger: ".o-mail-Composer button[aria-label='Log']:enabled", run: "click" },
        { trigger: ".o-mail-Message:contains('Internal note from tour')" },
    ],
});
