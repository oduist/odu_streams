import {
    click,
    contains,
    listenStoreFetch,
    start,
    startServer,
    waitStoreFetch,
} from "@mail/../tests/mail_test_helpers";

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { advanceTime } from "@odoo/hoot-mock";

import { getService, mockService, serverState } from "@web/../tests/web_test_helpers";

import { BUS_COUNTER, BUS_NEW, defineStreamsModels } from "./streams_test_helpers";

describe.current.tags("desktop");
defineStreamsModels();

/** Элемент `mail.notify._streams_payload` — он же payload шины (А5). */
function notifyPayload(values = {}) {
    return {
        id: 1,
        date: "2026-08-19 10:00:00",
        author: { id: serverState.userId, name: "Mitchell Admin" },
        body: "<p>Deadline moved to Friday</p>",
        is_sticky: false,
        timeout: 5,
        res_model: false,
        res_id: false,
        record_name: "",
        attachments: [],
        voice: false,
        transcript: false,
        transcript_state: "none",
        parent_id: false,
        popup_shown: false,
        read_date: false,
        ...values,
    };
}

/**
 * Заглушка звука (E8).
 *
 * Сам факт проигрывания не проверяется: `playNotifySound` сначала ждёт
 * `multi_tab.isOnMainTab()`, выбор мастер-вкладки в Hoot асинхронен и
 * недетерминирован — шаг по нему был бы плавающим. Заглушка нужна, чтобы
 * тест не дёргал настоящий `<audio>`.
 */
function mockNotifySound() {
    mockService("mail.sound_effects", {
        play() {},
    });
}

/** Партнёр текущего пользователя — адресат bus-рассылки. */
function selfPartner(pyEnv) {
    return pyEnv["res.partner"].read(serverState.partnerId)[0];
}

test("попап всплывает по пушу streams.notify/new и гаснет по таймауту", async () => {
    const pyEnv = await startServer();
    mockNotifySound();
    listenStoreFetch("init_messaging");
    await start();
    // подписка на шину заводится после init_messaging
    await waitStoreFetch("init_messaging");
    pyEnv["bus.bus"]._sendone(selfPartner(pyEnv), BUS_NEW, notifyPayload({ counter: 1 }));
    await contains(".o-streams-NotifyPopup");
    await contains(".o-streams-NotifyCard-body", { text: "Deadline moved to Friday" });
    await contains(".o-streams-NotifyCard-author", { text: "Mitchell Admin" });
    // бейдж колокола ведёт себя как счётчик из того же пуша
    await contains(".o-streams-NotifyMenu-counter", { text: "1" });
    await advanceTime(5000);
    await contains(".o-streams-NotifyPopup", { count: 0 });
});

test("sticky-попап не гаснет и складывается в стек с пагинатором", async () => {
    const pyEnv = await startServer();
    mockNotifySound();
    listenStoreFetch("init_messaging");
    await start();
    await waitStoreFetch("init_messaging");
    const partner = selfPartner(pyEnv);
    pyEnv["bus.bus"]._sendone(
        partner,
        BUS_NEW,
        notifyPayload({ id: 1, is_sticky: true, body: "<p>First</p>" })
    );
    await contains(".o-streams-NotifyPopup.o-sticky");
    pyEnv["bus.bus"]._sendone(
        partner,
        BUS_NEW,
        notifyPayload({ id: 2, is_sticky: true, body: "<p>Second</p>" })
    );
    await contains(".o-streams-NotifyContainer-paginator");
    // самый свежий sticky показывается сразу (E5)
    expect(normalize(".o-streams-NotifyContainer-pagerValue")).toBe("2 / 2");
    await contains(".o-streams-NotifyCard-body", { text: "Second" });
    // sticky не гаснет сам — время его не касается
    await advanceTime(60_000);
    await contains(".o-streams-NotifyPopup.o-sticky");
    await click(".o-streams-NotifyContainer-paginator button[aria-label='Previous']");
    // именно `contains`, а не голый `expect`: ядровый `click` ждёт один
    // микротик, а перерисовка Owl приезжает кадром позже
    await contains(".o-streams-NotifyContainer-pagerValue", { text: "1 / 2" });
    await contains(".o-streams-NotifyCard-body", { text: "First" });
    // закрытие крестиком убирает карточку из стека
    await click(".o-streams-NotifyPopup-close");
    await contains(".o-streams-NotifyContainer-paginator", { count: 0 });
    await contains(".o-streams-NotifyCard-body", { text: "Second" });
});

test("бейдж колокола обновляется пушем streams.notify/counter", async () => {
    const pyEnv = await startServer();
    listenStoreFetch("init_messaging");
    await start();
    await waitStoreFetch("init_messaging");
    const partner = selfPartner(pyEnv);
    await contains(".o-streams-NotifyMenu");
    await contains(".o-streams-NotifyMenu-counter", { count: 0 });
    pyEnv["bus.bus"]._sendone(partner, BUS_COUNTER, { counter: 3 });
    await contains(".o-streams-NotifyMenu-counter", { text: "3" });
    pyEnv["bus.bus"]._sendone(partner, BUS_COUNTER, { counter: 120 });
    await contains(".o-streams-NotifyMenu-counter", { text: "99+" });
    pyEnv["bus.bus"]._sendone(partner, BUS_COUNTER, { counter: 0 });
    await contains(".o-streams-NotifyMenu-counter", { count: 0 });
});

test("автор уведомления не перетирает одноимённого партнёра в Store", async () => {
    const pyEnv = await startServer();
    // id автора в payload'е — это id res.users (`mail.notify.author_id`), а
    // не партнёра: запись `mail.notify` не имеет права трактовать его как
    // партнёра, иначе Store подменит имя чужому контакту
    const partnerId = pyEnv["res.partner"].create({ name: "Some Customer" });
    mockNotifySound();
    listenStoreFetch("init_messaging");
    await start();
    await waitStoreFetch("init_messaging");
    getService("mail.store")["res.partner"].insert({ id: partnerId, name: "Some Customer" });
    pyEnv["bus.bus"]._sendone(
        selfPartner(pyEnv),
        BUS_NEW,
        notifyPayload({ author: { id: partnerId, name: "Notify Author" } })
    );
    await contains(".o-streams-NotifyCard-author", { text: "Notify Author" });
    expect(getService("mail.store")["res.partner"].get(partnerId).name).toBe("Some Customer");
});

/**
 * Текст элемента со схлопнутыми пробелами: в шаблоне пагинатора значения
 * разнесены переносами строк.
 *
 * @param {string} selector
 */
function normalize(selector) {
    return queryOne(selector).textContent.replace(/\s+/g, " ").trim();
}
