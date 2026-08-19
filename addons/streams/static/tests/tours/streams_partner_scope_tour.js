import { registry } from "@web/core/registry";

/**
 * Переключатель охвата чаттера контакта (§18.2).
 *
 * Hoot проверяет разметку на mock-сервере с его игрушечным реестром;
 * здесь важно, что настоящая связка «реестр → SQL VIEW → ветка
 * `_message_fetch`» доносит до ленты сообщение чужой записи (лида) и
 * убирает его при переключении в Direct.
 */
registry.category("web_tour.tours").add("streams_partner_scope_tour", {
    steps: () => [
        { trigger: ".o-mail-Chatter-topbar" },
        // дефолт §18.2 — Related; у контакта организации доступны все три
        { trigger: ".o-streams-Chatter-scopeButton[data-streams-scope='company']" },
        { trigger: ".o-streams-Chatter-scopeButton[data-streams-scope='related'][aria-pressed='true']" },
        // виртуальное сообщение лида и ядровая ссылка на источник (Р5)
        { trigger: ".o-mail-Message:contains('Lead message for the scope tour')" },
        { trigger: ".o-mail-Message a:contains('Streams Scope Tour Lead')" },
        { trigger: ".o-mail-Message:contains('Contact own message for the scope tour')" },

        { trigger: ".o-streams-Chatter-scopeButton[data-streams-scope='direct']", run: "click" },
        { trigger: ".o-streams-Chatter-scopeButton[data-streams-scope='direct'][aria-pressed='true']" },
        // Direct — только сообщения самой карточки контакта
        {
            trigger:
                ".o-mail-Thread:not(:has(.o-mail-Message:contains('Lead message for the scope tour')))",
        },
        { trigger: ".o-mail-Message:contains('Contact own message for the scope tour')" },

        { trigger: ".o-streams-Chatter-scopeButton[data-streams-scope='related']", run: "click" },
        { trigger: ".o-streams-Chatter-scopeButton[data-streams-scope='related'][aria-pressed='true']" },
        { trigger: ".o-mail-Message:contains('Lead message for the scope tour')" },
    ],
});
