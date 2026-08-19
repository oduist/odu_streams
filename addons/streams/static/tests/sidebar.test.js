import {
    contains,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";

import { getService } from "@web/../tests/web_test_helpers";

import {
    createStreamsPersonalChannel,
    createStreamsRecordChannel,
    defineStreamsModels,
} from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

/** Категория сайдбара, в которую тред попал по `_computeDiscussAppCategory`. */
function categoryOf(channelId) {
    return getService("mail.store")
        .Thread.get({ model: "discuss.channel", id: channelId })
        ?.discussAppCategory?.id;
}

test("канал записи попадает в свою категорию Messages", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    const channelId = createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    await start();
    await openDiscuss();
    await contains(".o-mail-DiscussSidebarCategory.o-streams-DiscussSidebarCategory-messages");
    await contains(".o-mail-DiscussSidebarCategory-title", { text: "Messages" });
    await contains(".o-mail-DiscussSidebarChannel-itemName", { text: "John Doe" });
    expect(categoryOf(channelId)).toBe("streams.messages");
});

test("личные каналы Changes и Notifications остаются в ядровой Channels", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    const changesId = createStreamsPersonalChannel(pyEnv, "changes");
    const notificationsId = createStreamsPersonalChannel(pyEnv, "notifications");
    const recordId = createStreamsRecordChannel(pyEnv, {
        resModel: "res.partner",
        resId: partnerId,
        name: "John Doe",
    });
    await start();
    await openDiscuss();
    await contains(".o-mail-DiscussSidebarChannel-itemName", { count: 3 });
    // сайдбар плоский: заголовок категории и следом её каналы. Сравнивается
    // не весь список (ядро вольно добавлять свои категории), а раскладка
    // вокруг наших: Changes/Notifications — под Channels, канал записи —
    // под своей Messages (решение Р3)
    const sidebar = queryAllTexts(
        ".o-mail-DiscussSidebarCategory-title, .o-mail-DiscussSidebarChannel-itemName"
    );
    expect(sidebar.slice(sidebar.indexOf("Channels"), sidebar.indexOf("Channels") + 3)).toEqual([
        "Channels",
        "Changes",
        "Notifications",
    ]);
    expect(sidebar.slice(sidebar.indexOf("Messages"), sidebar.indexOf("Messages") + 2)).toEqual([
        "Messages",
        "John Doe",
    ]);
    expect(categoryOf(changesId)).toBe("channels");
    expect(categoryOf(notificationsId)).toBe("channels");
    expect(categoryOf(recordId)).toBe("streams.messages");
});

test("категория Messages не показывается, когда каналов записей нет", async () => {
    const pyEnv = await startServer();
    pyEnv["discuss.channel"].create({ name: "general" });
    await start();
    await openDiscuss();
    await contains(".o-mail-DiscussSidebarCategory-title", { text: "Channels" });
    await contains(".o-mail-DiscussSidebarCategory-title", { count: 0, text: "Messages" });
});
