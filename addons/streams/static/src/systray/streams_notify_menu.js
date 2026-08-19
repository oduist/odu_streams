import { Component, useState } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Колокол уведомлений в навбаре (§11.4, E10).
 *
 * Без выпадающего меню — как в клиенте 15: клик сразу открывает личный
 * канал Notifications, лента живёт там (§12.5). Дропдаун дублировал бы
 * ленту и разошёлся бы с ней по прочитанности.
 */
export class StreamsNotifyMenu extends Component {
    static props = [];
    static template = "streams.NotifyMenu";

    setup() {
        this.streamsCore = useService("streams.core");
        this.notifyState = useState(this.streamsCore.notifyState);
    }

    /** @type {string} бейдж; больше 99 не рисуем — не влезает. */
    get counterLabel() {
        return this.notifyState.counter > 99 ? "99+" : String(this.notifyState.counter);
    }

    onClick() {
        this.streamsCore.openNotifyChannel();
    }
}

// Порядок в навбаре: элементы сортируются по возрастанию sequence и
// разворачиваются (`web/…/navbar.js`, `systrayItems`), поэтому больший
// sequence оказывается левее. Discuss (`mail.messaging_menu`) — 25,
// значит 26 ставит колокол вплотную слева от него.
registry.category("systray").add(
    "streams.notify_menu",
    { Component: StreamsNotifyMenu },
    { sequence: 26 }
);
