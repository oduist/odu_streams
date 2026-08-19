import { Component, useState } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { StreamsNotifyCard } from "./streams_notify_card";

/**
 * Стек попапов уведомлений (§12.4, E3–E5).
 *
 * Свой контейнер, а не ядровый `notification`-сервис: тот принимает
 * только строку, держит фиксированный `autocloseDelay` и не умеет ни
 * стека sticky с пагинатором, ни плеера, ни кнопки Reply внутри
 * карточки. Монтируется в `main_components` — поэтому живёт поверх
 * всего webclient и переживает смену действия.
 */
export class StreamsNotifyContainer extends Component {
    static components = { StreamsNotifyCard };
    static props = [];
    static template = "streams.NotifyContainer";

    setup() {
        this.streamsCore = useService("streams.core");
        // useState, а не голый reactive сервиса: перерисовка компонента
        // подписывается именно через него
        this.notifyState = useState(this.streamsCore.notifyState);
    }

    /** @type {Object[]} попапы, которые гаснут по своему таймауту. */
    get transientPopups() {
        return this.notifyState.popups.filter((popup) => !popup.is_sticky);
    }

    /** @type {Object[]} */
    get stickyPopups() {
        return this.notifyState.popups.filter((popup) => popup.is_sticky);
    }

    /** @type {Object|undefined} текущая карточка sticky-стека. */
    get currentSticky() {
        const sticky = this.stickyPopups;
        if (!sticky.length) {
            return undefined;
        }
        return sticky[this.stickyPosition - 1];
    }

    /** @type {number} человекочитаемая позиция «N / M». */
    get stickyPosition() {
        const sticky = this.stickyPopups;
        if (!sticky.length) {
            return 0;
        }
        return (
            Math.min(Math.max(this.notifyState.stickyIndex, 0), sticky.length - 1) + 1
        );
    }

    onClickClose(popup) {
        this.streamsCore.closePopup(popup.id);
    }

    onClickReply(popup) {
        this.streamsCore.replyToNotify(popup.id);
        this.streamsCore.closePopup(popup.id);
    }

    onMouseEnter(popup) {
        this.streamsCore.pausePopup(popup.id);
    }

    onMouseLeave(popup) {
        this.streamsCore.resumePopup(popup.id);
    }

    onClickPrevious() {
        this.streamsCore.showStickyPopup(this.notifyState.stickyIndex - 1);
    }

    onClickNext() {
        this.streamsCore.showStickyPopup(this.notifyState.stickyIndex + 1);
    }
}

// sequence 110 — выше ядрового контейнера нотификаций (100): при равном
// z-index решает порядок монтирования, и наши карточки не оказываются
// под тостами.
registry.category("main_components").add(
    "streams.NotifyContainer",
    { Component: StreamsNotifyContainer },
    { sequence: 110 }
);
