import {
    click,
    contains,
    onRpcBefore,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";

import { asyncStep, onRpc, serverState, waitForSteps } from "@web/../tests/web_test_helpers";

import { defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

const SCOPE = ".o-streams-Chatter-scopeButton";

/** id подтипа `mail.mt_comment` в mock-сервере. */
function commentSubtypeId(pyEnv) {
    return pyEnv["mail.message.subtype"].search([["subtype_xmlid", "=", "mail.mt_comment"]])[0];
}

test("сегмент охвата на чаттере контакта организации", async () => {
    const pyEnv = await startServer();
    const companyId = pyEnv["res.partner"].create({ name: "Acme Inc" });
    const contactId = pyEnv["res.partner"].create({ name: "John Doe", parent_id: companyId });
    await start();
    await openFormView("res.partner", contactId);
    await contains(".o-streams-Chatter-scope");
    await contains(SCOPE, { count: 3 });
    expect(queryAllTexts(SCOPE)).toEqual(["Direct", "Related", "Company"]);
    // дефолт §18.2 — Related
    await contains(`${SCOPE}[data-streams-scope='related'][aria-pressed='true']`);
    await contains(`${SCOPE}[aria-pressed='true']`, { count: 1 });
});

test("Company скрыта у контакта без организации и дочерних контактов (Р11)", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Lone Wolf" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-streams-Chatter-scope");
    await contains(SCOPE, { count: 2 });
    expect(queryAllTexts(SCOPE)).toEqual(["Direct", "Related"]);
    await contains(`${SCOPE}[data-streams-scope='company']`, { count: 0 });
});

test("на чаттере не-контакта переключателя нет", async () => {
    const pyEnv = await startServer();
    const fakeId = pyEnv["res.fake"].create({ name: "Big Deal" });
    await start();
    await openFormView("res.fake", fakeId);
    await contains(".o-mail-Chatter-topbar");
    await contains(".o-streams-Chatter-scope", { count: 0 });
});

test("клик по Direct сохраняет настройку и перечитывает ленту", async () => {
    const pyEnv = await startServer();
    const companyId = pyEnv["res.partner"].create({ name: "Acme Inc" });
    const contactId = pyEnv["res.partner"].create({ name: "John Doe", parent_id: companyId });
    const fakeId = pyEnv["res.fake"].create({ name: "Big Deal", partner_id: contactId });
    const subtypeId = commentSubtypeId(pyEnv);
    pyEnv["mail.message"].create({
        author_id: serverState.partnerId,
        body: "Own message of the contact",
        message_type: "comment",
        model: "res.partner",
        res_id: contactId,
        subtype_id: subtypeId,
    });
    pyEnv["mail.message"].create({
        author_id: serverState.partnerId,
        body: "Virtual message of the lead",
        message_type: "comment",
        model: "res.fake",
        res_id: fakeId,
        subtype_id: subtypeId,
    });
    // счётчиком, а не шагами: на открытии формы лента тянется не один
    // раз, а проверяем мы именно перечитку ПОСЛЕ клика
    let fetchCount = 0;
    onRpcBefore("/mail/thread/messages", () => {
        fetchCount++;
    });
    onRpc("res.users.settings", "set_res_users_settings", ({ kwargs }) => {
        asyncStep(`set_res_users_settings:${JSON.stringify(kwargs.new_settings)}`);
    });
    await start();
    await openFormView("res.partner", contactId);
    await contains(SCOPE, { count: 3 });
    await contains(".o-mail-Message", { count: 2 });
    const fetchCountBefore = fetchCount;
    await click(`${SCOPE}[data-streams-scope='direct']`);
    // охват клиент в запросе ленты не передаёт (Р6): сначала запись
    // настройки, потом полная перечитка страницы
    await waitForSteps([
        `set_res_users_settings:${JSON.stringify({ streams_partner_scope: "direct" })}`,
    ]);
    await contains(`${SCOPE}[data-streams-scope='direct'][aria-pressed='true']`);
    // Direct — только сообщения самой карточки контакта; лента именно
    // перечитана, а не отфильтрована на клиенте (охват считает сервер)
    await contains(".o-mail-Message", { count: 1 });
    await contains(".o-mail-Message", { text: "Own message of the contact" });
    expect(fetchCount).toBeGreaterThan(fetchCountBefore);
});

test("ссылка «on <документ>» видна у сообщения чужой записи (Р5)", async () => {
    const pyEnv = await startServer();
    const contactId = pyEnv["res.partner"].create({ name: "John Doe" });
    const fakeId = pyEnv["res.fake"].create({ name: "Big Deal", partner_id: contactId });
    const subtypeId = commentSubtypeId(pyEnv);
    pyEnv["mail.message"].create({
        author_id: serverState.partnerId,
        body: "Own message of the contact",
        message_type: "comment",
        model: "res.partner",
        res_id: contactId,
        subtype_id: subtypeId,
    });
    pyEnv["mail.message"].create({
        author_id: serverState.partnerId,
        body: "Virtual message of the lead",
        message_type: "comment",
        model: "res.fake",
        res_id: fakeId,
        subtype_id: subtypeId,
    });
    await start();
    await openFormView("res.partner", contactId);
    // охват по умолчанию Related — в ленте обе записи
    await contains(".o-mail-Message", { count: 2 });
    await contains(".o-mail-Message", { text: "Virtual message of the lead" });
    // наш `message_patch.js` ссылку здесь не прячет: он срабатывает
    // только в канале записи (`channel_kind === "record"`), а у треда
    // чаттера этого признака нет
    await contains(".o-mail-Message a", { text: "Big Deal" });
});
