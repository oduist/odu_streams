import { registry } from "@web/core/registry";

/**
 * Композер приоритетного уведомления (§12.2, решение Р5).
 *
 * Тур доводит сценарий до серверной отправки и тоста. Попап у получателя
 * здесь не проверить: он всплывает в сессии ДРУГОГО пользователя, а тур
 * живёт в одной. Эта половина закрыта Hoot-тестом
 * (`static/tests/notify_popup.test.js`, пуш `streams.notify/new`) и
 * серверными тестами доставки (`tests/test_streams_notify.py`).
 */
registry.category("web_tour.tours").add("streams_notify_tour", {
    steps: () => [
        { trigger: "button.o-streams-Chatter-notify", run: "click" },
        { trigger: ".o-streams-NotifyComposer" },
        // отправка заблокирована, пока нет получателя (F9)
        { trigger: ".o-streams-NotifyComposer-send:disabled" },
        { trigger: ".o-streams-NotifyComposer-search", run: "edit Streams Tour Mate" },
        {
            trigger: ".o-streams-NotifyComposer-result:contains('Streams Tour Mate')",
            run: "click",
        },
        { trigger: ".o-streams-NotifyComposer-chip:contains('Streams Tour Mate')" },
        { trigger: ".o-streams-NotifyComposer-body", run: "edit Please check this record" },
        { trigger: ".o-streams-NotifyComposer-send:enabled", run: "click" },
        { trigger: ".o_notification:contains('Notification sent.')" },
    ],
});
