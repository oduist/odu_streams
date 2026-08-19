import { registry } from "@web/core/registry";

/**
 * Канал записи в Discuss (§11.2, §11.3).
 *
 * Канал заводится фикстурой python-теста (первое сообщение на записи —
 * первый триггер §5.1), поэтому тур начинается с уже готового сайдбара.
 */
registry.category("web_tour.tours").add("streams_channel_tour", {
    steps: () => [
        // своя категория сайдбара — ровно одна (решение Р3)
        { trigger: ".o-mail-DiscussSidebarCategory.o-streams-DiscussSidebarCategory-messages" },
        {
            trigger:
                ".o-mail-DiscussSidebarChannel-itemName:contains('Streams Tour Record')",
            run: "click",
        },
        { trigger: ".o-mail-DiscussContent-threadName[title='Streams Tour Record']" },

        { trigger: ".o-mail-Composer-input", run: "edit Comment from the record channel" },
        { trigger: ".o-mail-Composer button[aria-label='Send']:enabled", run: "click" },
        { trigger: ".o-mail-Message:contains('Comment from the record channel')" },

        // панель фильтров: выключить поток Notes и вернуть обратно (§6, A6)
        { trigger: "button[title='Streams']", run: "click" },
        {
            trigger: ".o-streams-FilterPanel-toggle[data-streams-filter='note'][aria-pressed='true']",
            run: "click",
        },
        {
            trigger:
                ".o-streams-FilterPanel-toggle[data-streams-filter='note'][aria-pressed='false']",
            run: "click",
        },
        {
            trigger:
                ".o-streams-FilterPanel-toggle[data-streams-filter='note'][aria-pressed='true']",
        },
    ],
});
