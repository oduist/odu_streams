import {
    click,
    contains,
    insertText,
    onRpcBefore,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, test } from "@odoo/hoot";

import { asyncStep, mockService, waitForSteps } from "@web/../tests/web_test_helpers";

import { defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
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

/** Подтип каждой отправки — из параметров реального роута постинга. */
function stepSubtypeOnPost() {
    onRpcBefore("/mail/message/post", (args) => {
        asyncStep(`post:${args.post_data.subtype_xmlid}`);
    });
}

test("кнопки streams в топбаре чаттера записи", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Chatter-topbar");
    // фаза 9.5: ядровые Comment/Note убраны — их работу (открыть композер)
    // делать больше нечего, композер открыт всегда
    await contains("button.o-mail-Chatter-sendMessage", { count: 0 });
    await contains("button.o-mail-Chatter-logNote", { count: 0 });
    // свои кнопки (B3/B5/B6/B7), подписи укорочены фазой 9.5
    await contains("button.o-streams-Chatter-sendExternal", { text: "Message" });
    await contains("button.o-streams-Chatter-notify", { text: "Notify" });
    await contains("button.o-streams-Chatter-changes", { text: "Changes" });
    await contains("button.o-streams-Chatter-invite", { text: "Invite" });
});

test("композер открыт сразу, с плейсхолдером внутреннего комментария", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    // ни одного клика: композер должен быть на экране сам (фаза 9.5)
    await contains(".o-mail-Composer");
    await contains(".o-mail-Composer-input[placeholder='Post an internal comment…']");
    // две кнопки отправки в футере: ядровая Send и наша Note
    await contains(".o-mail-Composer button[aria-label='Send']");
    await contains(".o-mail-Composer button.o-streams-Composer-note", { text: "Note" });
});

test("кнопки отправки неактивны, пока нечего отправлять", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Composer button[aria-label='Send']:disabled");
    await contains("button.o-streams-Composer-note:disabled");
    await insertText(".o-mail-Composer-input", "Something to say");
    await contains(".o-mail-Composer button[aria-label='Send']:enabled");
    await contains("button.o-streams-Composer-note:enabled");
});

test("композер Comment не показывает строку получателей", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Composer");
    // ядро рисует «To: <получатели>» и рассылает им письмо; в streams
    // внутренний комментарий писем не шлёт (§7)
    await contains(".o-mail-RecipientsInput", { count: 0 });
    await contains(".o-mail-Chatter-top", { count: 0, text: "To:" });
});

test("Send шлёт комментарий и оставляет композер открытым и пустым", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    stepSubtypeOnPost();
    await start();
    await openFormView("res.partner", partnerId);
    await insertText(".o-mail-Composer-input", "Internal comment");
    await click(".o-mail-Composer button[aria-label='Send']");
    await waitForSteps(["post:mail.mt_comment"]);
    await contains(".o-mail-Message-body", { text: "Internal comment" });
    // фаза 9.5: ядро закрывало композер после отправки — теперь он
    // остаётся на экране, очищенный
    await contains(".o-mail-Composer");
    await contains(".o-mail-Composer-input", { value: "" });
});

test("Note шлёт тот же текст заметкой", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    stepSubtypeOnPost();
    await start();
    await openFormView("res.partner", partnerId);
    await insertText(".o-mail-Composer-input", "Internal note");
    await click("button.o-streams-Composer-note");
    await waitForSteps(["post:mail.mt_note"]);
    await contains(".o-mail-Message-body", { text: "Internal note" });
    await contains(".o-mail-Composer");
    await contains(".o-mail-Composer-input", { value: "" });
});

test("Note — разовая отправка, а не режим: следующая Send снова комментарий", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    stepSubtypeOnPost();
    await start();
    await openFormView("res.partner", partnerId);
    await insertText(".o-mail-Composer-input", "First as note");
    await click("button.o-streams-Composer-note");
    await waitForSteps(["post:mail.mt_note"]);
    // Дождаться, пока улягутся перерисовки отправки, и только потом
    // печатать второй раз. Чаттер после `message_post` перечитывает и
    // ленту, и родительскую запись; `insertText` пишет прямо в
    // `el.value`, и перерисовка, попавшая в его `animationFrame`, стирает
    // напечатанное обратно в пустой `composerText`. Живьём этого нет
    // (проверено в браузере), артефакт хелпера.
    await contains(".o-mail-Message-body", { text: "First as note" });
    await contains(".o-mail-Composer-input", { value: "" });
    await insertText(".o-mail-Composer-input", "Second as comment");
    await click(".o-mail-Composer button[aria-label='Send']:enabled");
    await waitForSteps(["post:mail.mt_comment"]);
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

test("Message открывает полный композер с подтипом streams.mt_message", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    mockStreamsActions();
    await start();
    await openFormView("res.partner", partnerId);
    await click("button.o-streams-Chatter-sendExternal");
    await waitForSteps(["mail.compose.message:streams.mt_message"]);
});

test("Invite открывает визард гостевого доступа", async () => {
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
