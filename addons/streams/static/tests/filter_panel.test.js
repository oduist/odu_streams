import {
    click,
    contains,
    onRpcBefore,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { queryAllAttributes, queryAllTexts } from "@odoo/hoot-dom";

import { asyncStep, onRpc, waitForSteps } from "@web/../tests/web_test_helpers";

import { createStreamsRecordChannel, defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

test("панель фильтров: пять тумблеров в порядке клиента 15", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    const channelId = createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    await start();
    await openDiscuss(channelId);
    await click("button[title='Streams']");
    await contains(".o-streams-FilterPanel");
    await contains(".o-streams-FilterPanel-toggle", { count: 5 });
    expect(queryAllAttributes(".o-streams-FilterPanel-toggle", "data-streams-filter")).toEqual([
        "comment",
        "note",
        "message",
        "change",
        "activity",
    ]);
    expect(queryAllTexts(".o-streams-FilterPanel-toggle")).toEqual([
        "Comments",
        "Notes",
        "Customers",
        "Changes",
        "Activities",
    ]);
    // дефолты §6: выключен только поток change
    expect(queryAllAttributes(".o-streams-FilterPanel-toggle", "aria-pressed")).toEqual([
        "true",
        "true",
        "true",
        "false",
        "true",
    ]);
});

test("панели фильтров нет у обычного канала Discuss", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "general" });
    await start();
    await openDiscuss(channelId);
    await contains(".o-mail-Discuss");
    await contains("button[title='Streams']", { count: 0 });
});

test("клик по тумблеру сохраняет фильтры и перечитывает ленту", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    const channelId = createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    // счётчиком, а не шагами: на открытии канала лента может тянуться не
    // один раз, а проверяем мы именно перечитку ПОСЛЕ клика
    let fetchCount = 0;
    onRpcBefore("/discuss/channel/messages", () => {
        fetchCount++;
    });
    onRpc("discuss.channel", "streams_set_filters", ({ kwargs }) => {
        asyncStep(`streams_set_filters:${JSON.stringify(kwargs.filters)}`);
    });
    await start();
    await openDiscuss(channelId);
    await click("button[title='Streams']");
    await contains(".o-streams-FilterPanel-toggle", { count: 5 });
    const fetchCountBefore = fetchCount;
    await click(".o-streams-FilterPanel-toggle[data-streams-filter='change']");
    // фильтрация серверная (решение Р1): сохранить и перечитать страницу
    await waitForSteps([`streams_set_filters:${JSON.stringify({ change: true })}`]);
    await contains(
        ".o-streams-FilterPanel-toggle[data-streams-filter='change'][aria-pressed='true']"
    );
    expect(fetchCount).toBeGreaterThan(fetchCountBefore);
});
