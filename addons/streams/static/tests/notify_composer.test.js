import {
    click,
    contains,
    insertText,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { advanceTime } from "@odoo/hoot-mock";

import { asyncStep, onRpc, waitForSteps } from "@web/../tests/web_test_helpers";

import { defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

/**
 * Внутренний пользователь-получатель.
 *
 * @param {Object} pyEnv
 * @param {string} name
 * @returns {number} id пользователя
 */
function createInternalUser(pyEnv, name) {
    const partnerId = pyEnv["res.partner"].create({ name });
    return pyEnv["res.users"].create({ partner_id: partnerId, login: name });
}

/**
 * Открыть композер Notify кнопкой чаттера.
 *
 * @param {Object} pyEnv
 * @returns {Promise<number>} id записи-источника
 */
async function openComposerFromChatter(pyEnv) {
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await click("button.o-streams-Chatter-notify");
    await contains(".o-streams-NotifyComposer");
    return partnerId;
}

test("поиск получателей: дебаунс, домен и чипы", async () => {
    const pyEnv = await startServer();
    const userId = createInternalUser(pyEnv, "Marc Demo");
    onRpc("res.users", "name_search", ({ kwargs }) => {
        asyncStep(`name_search:${kwargs.name}:${JSON.stringify(kwargs.domain)}`);
        return [[userId, "Marc Demo"]];
    });
    await openComposerFromChatter(pyEnv);
    // именно `insertText`, а не `click` + `edit`: ядровый `click` из
    // `mail_test_helpers` только рассылает focus-события, но не зовёт
    // `el.focus()`, а `edit()` из hoot печатает в `document.activeElement`
    // — то есть в поле, которое сфокусировал `Dialog` при открытии
    await insertText(".o-streams-NotifyComposer-search", "Marc");
    // поиск дебаунсится на 300 мс (F1)
    await advanceTime(300);
    await waitForSteps([
        `name_search:Marc:${JSON.stringify([
            ["share", "=", false],
            ["active", "=", true],
            ["id", "not in", []],
        ])}`,
    ]);
    await contains(".o-streams-NotifyComposer-result", { text: "Marc Demo" });
    await click(".o-streams-NotifyComposer-result");
    // `:contains`, а не `{text}`: в текст чипа входит и крестик удаления
    await contains(".o-streams-NotifyComposer-chip:contains('Marc Demo')");
    // выбранный получатель уходит из подсказки
    await contains(".o-streams-NotifyComposer-result", { count: 0 });
});

test("sticky прячет поле таймаута", async () => {
    const pyEnv = await startServer();
    await openComposerFromChatter(pyEnv);
    // дефолт таймаута приезжает в стартовом payload'е (E1)
    expect(queryOne(".o-streams-NotifyComposer-timeout").value).toBe("10");
    await click(".o-streams-NotifyComposer-sticky input");
    await contains(".o-streams-NotifyComposer-timeout", { count: 0 });
    await contains(".o-streams-NotifyComposer-hint", {
        text: "The popup stays until the recipient closes it.",
    });
    await click(".o-streams-NotifyComposer-sticky input");
    await contains(".o-streams-NotifyComposer-timeout");
});

test("отправка уведомления по записи: получатели, тело и тост", async () => {
    const pyEnv = await startServer();
    const userId = createInternalUser(pyEnv, "Marc Demo");
    onRpc("res.users", "name_search", () => [[userId, "Marc Demo"]]);
    onRpc("mail.notify", "streams_notify_send", ({ args }) => {
        asyncStep(`send:${JSON.stringify(args[0])}`);
    });
    const partnerId = await openComposerFromChatter(pyEnv);
    // без получателя отправка заблокирована (F9)
    await contains(".o-streams-NotifyComposer-send:disabled");
    await insertText(".o-streams-NotifyComposer-search", "Marc");
    await advanceTime(300);
    await click(".o-streams-NotifyComposer-result");
    await insertText(".o-streams-NotifyComposer-body", "Deadline moved to Friday");
    await click(".o-streams-NotifyComposer-send:enabled");
    await waitForSteps([
        `send:${JSON.stringify({
            body: "Deadline moved to Friday",
            attachment_ids: [],
            is_sticky: false,
            timeout: 10,
            res_model: "res.partner",
            res_id: partnerId,
            user_ids: [userId],
        })}`,
    ]);
    await contains(".o_notification_content", { text: "Notification sent." });
    await contains(".o-streams-NotifyComposer", { count: 0 });
});

// Голосовая запись (§12.3, F5) в Hoot не проверяется: ядровый
// `useVoiceRecorder` работает через `AudioWorklet` и загрузку lamejs,
// которых в тестовом окружении нет. Ближайшая точка автоматизации —
// ядровый хелпер `patchVoiceMessageAudio()` из `mail_test_helpers`; он
// подменяет весь Web Audio API, но проверял бы ядро, а не наш композер.
// Сценарий закрыт живой проверкой в среде и серверными тестами
// (`tests/test_streams_notify_upload.py`).
