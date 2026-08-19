import {
    click,
    contains,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";

import { asyncStep, getService, onRpc, waitForSteps } from "@web/../tests/web_test_helpers";

import { createStreamsPersonalChannel, defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

/**
 * Элемент ленты Changes в форме сервера
 * (`discuss.channel.streams_changes_feed`).
 *
 * @param {Object} values
 */
function changesItem(values = {}) {
    return {
        res_model: "res.partner",
        res_id: 11,
        record_name: "John Doe",
        last_message_id: 100,
        unread: false,
        changes: [
            {
                message_id: 100,
                date: "2026-08-19 10:00:00",
                author: "Mitchell Admin",
                author_id: 2,
                values: [
                    {
                        field_id: 7,
                        field_name: "function",
                        field_desc: "Job Position",
                        old: "Developer",
                        new: "Architect",
                    },
                ],
            },
        ],
        ...values,
    };
}

test("лента Changes рисует «поле: было → стало»", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "changes");
    onRpc("discuss.channel", "streams_changes_feed", () => ({
        items: [changesItem()],
        cursor: null,
        has_more: false,
    }));
    await start();
    await openDiscuss(channelId);
    await contains(".o-streams-ChangesFeed");
    await contains(".o-streams-ChangesFeed-item", { count: 1 });
    await contains(".o-streams-ChangesFeed-recordName", { text: "John Doe" });
    await contains(".o-streams-ChangesFeed-author", { text: "Mitchell Admin" });
    await contains(".o-streams-ChangesFeed-field", { text: "Job Position:" });
    await contains(".o-streams-ChangesFeed-old", { text: "Developer" });
    await contains(".o-streams-ChangesFeed-new", { text: "Architect" });
    // ленте нечего догружать — кнопки нет
    await contains(".o-streams-ChangesFeed-loadMore", { count: 0 });
    // A19: ядровые Thread/Composer для личного канала Changes не строятся
    await contains(".o-mail-Thread", { count: 0 });
    await contains(".o-mail-Composer", { count: 0 });
});

test("Load More листает по серверному курсору, пустая страница не гасит кнопку", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "changes");
    const pages = [
        // первая страница
        { items: [changesItem()], cursor: 100, has_more: true },
        // вся страница отсеяна подпиской/правами (§8.4), но хвост есть
        { items: [], cursor: 60, has_more: true },
        // последняя страница
        {
            items: [changesItem({ res_id: 12, record_name: "Jane Roe", last_message_id: 50 })],
            cursor: null,
            has_more: false,
        },
    ];
    let page = 0;
    onRpc("discuss.channel", "streams_changes_feed", ({ kwargs }) => {
        asyncStep(`feed:${kwargs.before_id ?? "start"}`);
        return pages[page++];
    });
    await start();
    await openDiscuss(channelId);
    await waitForSteps(["feed:start"]);
    await contains(".o-streams-ChangesFeed-item", { count: 1 });
    await contains(".o-streams-ChangesFeed-loadMore");

    await click(".o-streams-ChangesFeed-loadMore");
    // курсор сервера, а не last_message_id последнего показанного элемента
    await waitForSteps(["feed:100"]);
    await contains(".o-streams-ChangesFeed-item", { count: 1 });
    // страница вышла пустой, но `has_more` держит кнопку живой
    await contains(".o-streams-ChangesFeed-loadMore");

    await click(".o-streams-ChangesFeed-loadMore");
    await waitForSteps(["feed:60"]);
    await contains(".o-streams-ChangesFeed-item", { count: 2 });
    await contains(".o-streams-ChangesFeed-recordName", { text: "Jane Roe" });
    await contains(".o-streams-ChangesFeed-loadMore", { count: 0 });
});

test("пустая лента Changes показывает подсказку", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "changes");
    await start();
    await openDiscuss(channelId);
    // дефолт mock-модели — пустая лента
    await contains(".o-streams-ChangesFeed-empty");
    await contains(".o-streams-ChangesFeed-item", { count: 0 });
});

test("streams_mark_read отмечает канал прочитанным до сообщения", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "changes");
    onRpc("discuss.channel", "streams_mark_read", ({ args, kwargs }) => {
        asyncStep(`mark_read:${JSON.stringify(args[0])}:${kwargs.last_message_id}`);
    });
    await start();
    await openDiscuss(channelId);
    await contains(".o-streams-ChangesFeed");
    // отметка по доскроллу опирается на IntersectionObserver, который в
    // Hoot ведёт себя нестабильно; проверяется сам серверный контракт
    // (решение Р4 фазы 8), на который доскролл и завязан
    const result = await getService("orm").call(
        "discuss.channel",
        "streams_mark_read",
        [[channelId]],
        { last_message_id: 100 }
    );
    await waitForSteps([`mark_read:${JSON.stringify([channelId])}:100`]);
    expect(result).toEqual({ unread: 0 });
});
