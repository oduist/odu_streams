/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const { Component } = owl;

/**
 * Иконка Notifications в навбаре (§11.4).
 *
 * Реестр systray сортирует по возрастанию, а навбар разворачивает список,
 * поэтому 50.5 ставит колокол вплотную СЛЕВА от иконки Discuss (50) и не
 * задевает ни connect_messagebox (51), ни veles_custom_reports (49).
 * Дропдауна нет намеренно: §11.4 требует переход в канал.
 */
export class StreamsNotifyMenu extends Component {

    setup() {
        super.setup();
        this.notifyService = useService('streams_notify');
        this.notifyService.bus.on('UPDATE', this, this.render);
    }

    willUnmount() {
        this.notifyService.bus.off('UPDATE', this);
    }

    get counter() {
        return this.notifyService.state.counter;
    }

    get counterLabel() {
        return this.counter > 99 ? '99+' : String(this.counter);
    }

    onClick() {
        this.notifyService.openChannel();
    }
}

StreamsNotifyMenu.template = 'streams.NotifyMenu';

registry.category('systray').add(
    'streams.NotifyMenu',
    { Component: StreamsNotifyMenu },
    { sequence: 50.5 });
