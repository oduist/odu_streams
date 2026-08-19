import {
    click,
    contains,
    defineMailModels,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, test } from "@odoo/hoot";

import { asyncStep, mockService, waitForSteps } from "@web/../tests/web_test_helpers";

import { defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineMailModels();
defineStreamsModels();

/**
 * Перехват действий, которые чаттер открывает визардами.
 *
 * `super.doAction` для них не зовётся намеренно: `mail.compose.message` и
 * `streams.field.subscription.wizard` в mock-сервере не описаны видами, и
 * проверяем мы не их форму, а сам факт и параметры вызова.
 */
function mockStreamsActions() {
    mockService("action", {
        doAction(action) {
            if (typeof action === "object" && action?.res_model?.startsWith("streams.")) {
                asyncStep(`${action.res_model}:${JSON.stringify(action.context)}`);
                return true;
            }
            if (action?.res_model === "mail.compose.message") {
                asyncStep(`mail.compose.message:${action.context.default_subtype_xmlid}`);
                return true;
            }
            return super.doAction(...arguments);
        },
    });
}

test("кнопки streams в топбаре чаттера записи", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Chatter-topbar");
    // ядровые кнопки переименованы, классы ядра сохранены (B1/B2)
    await contains("button.o-mail-Chatter-sendMessage", { text: "Comment" });
    await contains("button.o-mail-Chatter-logNote", { text: "Note" });
    await contains(".o-mail-Chatter-topbar button", { count: 0, text: "Send message" });
    await contains(".o-mail-Chatter-topbar button", { count: 0, text: "Log note" });
    // свои кнопки (B3/B5/B6/B7)
    await contains("button.o-streams-Chatter-sendExternal", { text: "Send Message" });
    await contains("button.o-streams-Chatter-notify", { text: "Notify" });
    await contains("button.o-streams-Chatter-changes", { text: "Changes" });
    await contains("button.o-streams-Chatter-invite", { text: "Invite customer" });
});

test("композер Comment не показывает строку получателей", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await click("button.o-mail-Chatter-sendMessage");
    await contains(".o-mail-Composer");
    // ядро рисует «To: <получатели>» и рассылает им письмо; в streams
    // внутренний комментарий писем не шлёт (§7)
    await contains(".o-mail-RecipientsInput", { count: 0 });
    await contains(".o-mail-Chatter-top", { count: 0, text: "To:" });
});

test("Changes открывает визард подписки по записи", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    mockStreamsActions();
    await start();
    await openFormView("res.partner", partnerId);
    await click("button.o-streams-Chatter-changes");
    await waitForSteps([
        `streams.field.subscription.wizard:${JSON.stringify({
            default_res_model: "res.partner",
            default_res_id: partnerId,
        })}`,
    ]);
});

test("Send Message открывает полный композер с подтипом streams.mt_message", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    mockStreamsActions();
    await start();
    await openFormView("res.partner", partnerId);
    await click("button.o-streams-Chatter-sendExternal");
    await waitForSteps(["mail.compose.message:streams.mt_message"]);
});

test("Invite customer открывает визард гостевого доступа", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    mockStreamsActions();
    await start();
    await openFormView("res.partner", partnerId);
    await click("button.o-streams-Chatter-invite");
    await waitForSteps([
        `streams.guest.invite.wizard:${JSON.stringify({
            default_res_model: "res.partner",
            default_res_id: partnerId,
        })}`,
    ]);
});
