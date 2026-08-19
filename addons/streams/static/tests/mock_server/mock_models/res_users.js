import { mailModels } from "@mail/../tests/mail_test_helpers";

/**
 * Стартовый payload Notify в глобальных значениях Store (E1).
 *
 * На сервере это `res.users._init_store_data` →
 * `store.add_global_values(streams_notify=...)`; на клиенте значение
 * ловит `core/common/streams_init.js`. Плоский объект в `store.add()` —
 * ровно то, как mock-сервер кладёт глобальные значения.
 */
export class ResUsers extends mailModels.ResUsers {
    _init_store_data(store) {
        /** @type {import("mock_models").MailNotify} */
        const MailNotify = this.env["mail.notify"];

        super._init_store_data(...arguments);
        if (!this._is_public(this.env.uid)) {
            store.add({ streams_notify: MailNotify._streams_init_messaging() });
        }
    }
}
