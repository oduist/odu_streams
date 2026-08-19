import { click, contains, openDiscuss, start, startServer } from "@mail/../tests/mail_test_helpers";

import { describe, test } from "@odoo/hoot";

import { asyncStep, mockService, waitForSteps } from "@web/../tests/web_test_helpers";

import { createStreamsRecordChannel, defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

/**
 * Перехват открытия формы записи.
 *
 * `super.doAction` не зовём: видов `res.partner` в mock-сервере нет, а
 * проверяется сам факт и параметры перехода на запись-источник.
 */
function mockOpenDocument() {
    mockService("action", {
        doAction(action) {
            if (action?.type === "ir.actions.act_window") {
                asyncStep(`open:${action.res_model}:${action.res_id}`);
                return true;
            }
            return super.doAction(...arguments);
        },
    });
}

test("Open Record в шапке канала записи открывает запись-источник", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    const channelId = createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    mockOpenDocument();
    await start();
    await openDiscuss(channelId);
    await click("button[title='Open Record']");
    await waitForSteps([`open:res.partner:${partnerId}`]);
});

test("Open Record есть и в мини-меню канала в сайдбаре", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    mockOpenDocument();
    await start();
    await openDiscuss();
    await contains(".o-mail-DiscussSidebarChannel-itemName", { text: "John Doe" });
    await click("[title='Channel Actions']");
    await click(".o-dropdown-item:contains('Open Record')");
    await waitForSteps([`open:res.partner:${partnerId}`]);
});

test("у обычного канала Discuss пункта Open Record нет", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "general" });
    await start();
    await openDiscuss(channelId);
    await contains(".o-mail-Discuss");
    await contains("button[title='Open Record']", { count: 0 });
    await click("[title='Channel Actions']");
    await contains(".o-dropdown-item", { text: "Advanced Settings" });
    await contains(".o-dropdown-item:contains('Open Record')", { count: 0 });
});

test("ссылка под приветствием канала записи открывает запись", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    const channelId = createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    mockOpenDocument();
    await start();
    await openDiscuss(channelId);
    // ядровое приветствие пустого канала («This is the start of the
    // #John Doe channel») и сразу под ним — наша ссылка
    await contains("p", { text: "This is the start of the #John Doe channel" });
    await click(".o-streams-Thread-recordLink");
    await waitForSteps([`open:res.partner:${partnerId}`]);
});

test("у обычного канала ссылки на запись под приветствием нет", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "general" });
    await start();
    await openDiscuss(channelId);
    await contains("p", { text: "This is the start of the #general channel" });
    await contains(".o-streams-Thread-recordLink", { count: 0 });
});
