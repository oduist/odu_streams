import {
    click,
    contains,
    defineMailModels,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";

import {
    Command,
    asyncStep,
    getService,
    onRpc,
    serverState,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

import { createStreamsPersonalChannel, defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineMailModels();
defineStreamsModels();

/**
 * Уведомление, адресованное текущему пользователю.
 *
 * @param {Object} pyEnv
 * @param {Object} [values]
 * @returns {number}
 */
function createNotify(pyEnv, values = {}) {
    return pyEnv["mail.notify"].create({
        author_id: serverState.userId,
        body: "<p>Deadline moved to Friday</p>",
        // `popup_shown` — чтобы фикстура не всплывала попапом на старте:
        // проверяется лента, а не стек попапов
        recipient_ids: [Command.create({ user_id: serverState.userId, popup_shown: true })],
        ...values,
    });
}

test("лента Notifications переключает Received и Sent", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "notifications");
    createNotify(pyEnv);
    onRpc("mail.notify", "streams_notify_feed", ({ kwargs }) => {
        asyncStep(`feed:${kwargs.box}`);
    });
    await start();
    await openDiscuss(channelId);
    await contains(".o-streams-NotifyFeed");
    await waitForSteps(["feed:received"]);
    await contains(".o-streams-NotifyFeed-item", { count: 1 });
    await contains(".o-streams-NotifyCard-body", { text: "Deadline moved to Friday" });
    // во вкладке Received карточка предлагает ответить (§12.6)
    await contains(".o-streams-NotifyFeed-reply");
    await contains(".o-streams-NotifyFeed-recipient", { count: 0 });

    await click(".o-streams-NotifyFeed-boxButton[name='sent']");
    await waitForSteps(["feed:sent"]);
    // во вкладке Sent — состояние доставки каждому получателю
    await contains(".o-streams-NotifyFeed-recipient", { count: 1 });
    await contains(".o-streams-NotifyFeed-unread", { text: "Unread" });
    await contains(".o-streams-NotifyFeed-reply", { count: 0 });
});

test("ядровый ThreadView для канала Notifications не строится", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "notifications");
    await start();
    await openDiscuss(channelId);
    await contains(".o-streams-NotifyFeed");
    // A19: уведомления — не `mail.message`, ленты и композера ядра здесь нет
    await contains(".o-mail-Thread", { count: 0 });
    await contains(".o-mail-Composer", { count: 0 });
});

test("markNotifyRead шлёт streams_notify_mark_read и сбрасывает счётчик", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "notifications");
    const notifyId = createNotify(pyEnv);
    onRpc("mail.notify", "streams_notify_mark_read", ({ args }) => {
        asyncStep(`mark_read:${JSON.stringify(args[0])}`);
    });
    await start();
    await openDiscuss(channelId);
    await contains(".o-streams-NotifyFeed-item", { count: 1 });
    // прочитанность по доскроллу (IntersectionObserver) в Hoot нестабильна —
    // проверяется публичный метод сервиса, который она и вызывает
    await contains(".o-streams-NotifyMenu-counter", { text: "1" });
    const result = await getService("streams.core").markNotifyRead([notifyId]);
    await waitForSteps([`mark_read:${JSON.stringify([notifyId])}`]);
    expect(result.counter).toBe(0);
    await contains(".o-streams-NotifyMenu-counter", { count: 0 });
});

test("Mute сохраняет персональную настройку звука", async () => {
    const pyEnv = await startServer();
    const channelId = createStreamsPersonalChannel(pyEnv, "notifications");
    onRpc("res.users.settings", "set_res_users_settings", ({ kwargs }) => {
        asyncStep(`settings:${JSON.stringify(kwargs.new_settings)}`);
    });
    await start();
    await openDiscuss(channelId);
    await contains(".o-streams-NotifyFeed-muteButton .fa-volume-up");
    await click(".o-streams-NotifyFeed-muteButton");
    await waitForSteps([`settings:${JSON.stringify({ is_streams_notify_sound_muted: true })}`]);
    await contains(".o-streams-NotifyFeed-muteButton .fa-volume-off");
});
