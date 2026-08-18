/** @odoo-module **/

const { Component } = owl;

/**
 * Стек попапов уведомлений (§12.4).
 *
 * Не-sticky карточки складываются в колонку и гаснут по своему таймауту,
 * sticky — в стек с пагинатором: закрывается только текущая. Компонент
 * монтируется через категорию `main_components`, поэтому живёт поверх
 * всего webclient и не зависит от текущего действия.
 */
export class StreamsNotifyContainer extends Component {

    setup() {
        super.setup();
        this.props.bus.on('UPDATE', this, this.render);
    }

    willUnmount() {
        this.props.bus.off('UPDATE', this);
    }

    //----------------------------------------------------------------------
    // Данные
    //----------------------------------------------------------------------

    get service() {
        return this.props.service;
    }

    get transientPopups() {
        return this.props.state.popups.filter(popup => !popup.data.is_sticky);
    }

    get stickyPopups() {
        return this.props.state.popups.filter(popup => popup.data.is_sticky);
    }

    get currentSticky() {
        const sticky = this.stickyPopups;
        if (!sticky.length) {
            return undefined;
        }
        const index = Math.min(
            Math.max(this.props.state.stickyIndex, 0), sticky.length - 1);
        return sticky[index];
    }

    get stickyPosition() {
        return Math.min(
            Math.max(this.props.state.stickyIndex, 0),
            Math.max(this.stickyPopups.length - 1, 0)) + 1;
    }

    formatDate(value) {
        if (!value) {
            return '';
        }
        return moment.utc(value).local().format('LT');
    }

    formatDuration(seconds) {
        const total = Math.max(parseInt(seconds || 0, 10), 0);
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return minutes + ':' + (rest < 10 ? '0' : '') + rest;
    }

    attachmentUrl(attachmentId) {
        return '/web/content/' + attachmentId + '?download=true';
    }

    voiceUrl(attachmentId) {
        return '/web/content/' + attachmentId;
    }

    //----------------------------------------------------------------------
    // Действия
    //----------------------------------------------------------------------

    onClickClose(ev) {
        this.service.close(parseInt(ev.currentTarget.dataset.notifyId, 10));
    }

    onClickReply(ev) {
        const id = parseInt(ev.currentTarget.dataset.notifyId, 10);
        const popup = this.props.state.popups.find(entry => entry.id === id);
        if (!popup) {
            return;
        }
        this.service.reply(popup.data);
        this.service.close(id);
    }

    onClickRecord(ev) {
        ev.preventDefault();
        const { resModel, resId } = ev.currentTarget.dataset;
        this.service.openRecord(resModel, parseInt(resId, 10));
    }

    onMouseEnter(ev) {
        this.service.pause(parseInt(ev.currentTarget.dataset.notifyId, 10));
    }

    onMouseLeave(ev) {
        this.service.resume(parseInt(ev.currentTarget.dataset.notifyId, 10));
    }

    onClickPrevious() {
        this.service.showSticky(this.props.state.stickyIndex - 1);
    }

    onClickNext() {
        this.service.showSticky(this.props.state.stickyIndex + 1);
    }
}

StreamsNotifyContainer.template = 'streams.NotifyPopupContainer';
StreamsNotifyContainer.props = {
    bus: Object,
    state: Object,
    service: Object,
};
