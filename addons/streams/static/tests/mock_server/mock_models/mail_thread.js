import { mailModels } from "@mail/../tests/mail_test_helpers";

import { getKwArgs } from "@web/../tests/web_test_helpers";

/**
 * Данные треда чаттера: признак доступности охвата Company (§18.2, Р11).
 *
 * Почему здесь, а не в mock-модели `res.partner`: mock-сервер зовёт
 * ровно `env["mail.thread"]._thread_to_store.call(record, …)`
 * (`mail/static/tests/mock_server/mail_mock_server.js`), то есть метод
 * базового миксина с подменённым `this` — переопределение на конкретной
 * модели он бы не увидел.
 *
 * Ключ, как и на сервере (`models/res_partner.py`), кладётся только на
 * запрос данных треда (`request_list`): `store.add(…, as_thread=true)`
 * повторно входит в этот же метод.
 */
export class MailThread extends mailModels.MailThread {
    _thread_to_store(store, fields, request_list) {
        const kwargs = getKwArgs(arguments, "store", "fields", "request_list");
        super._thread_to_store(...arguments);
        if (this._name !== "res.partner" || !kwargs.request_list) {
            return;
        }
        /** @type {import("mock_models").ResPartner} */
        const ResPartner = this.env["res.partner"];
        const [partner] = ResPartner.browse(this[0].id);
        const available =
            Boolean(partner.parent_id) ||
            ResPartner.search_count([["parent_id", "=", partner.id]]) > 0;
        kwargs.store._add_record_fields(
            ResPartner.browse(partner.id),
            { streams_company_scope_available: available },
            true
        );
    }
}
