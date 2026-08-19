import { mailModels } from "@mail/../tests/mail_test_helpers";
import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";

import { Domain } from "@web/core/domain";
import { getKwArgs, makeKwArgs } from "@web/../tests/web_test_helpers";

/** Подтипы streams (`data/mail_message_subtype_data.xml`). */
const STREAMS_SUBTYPES = {
    "streams.mt_change": "change",
    "streams.mt_activity": "activity",
    "streams.mt_message": "message",
};

/**
 * Mock-реестр «модель → хранимое m2o-поле на res.partner» (§18.3).
 *
 * Заменяет собой таблицу `streams.partner.source` и SQL VIEW: в
 * mock-сервере ни того, ни другого нет. `res.fake` — ядровая тестовая
 * модель с чаттером и полем `partner_id`, то есть точный аналог
 * `crm.lead.partner_id` из сида (Р9).
 */
export const STREAMS_PARTNER_SOURCES = [["res.fake", "partner_id"]];

/** Потоки, попадающие в виртуальную часть ленты (Р7). */
const STREAMS_VIRTUAL_KINDS = ["comment", "note", "message", "activity"];

/**
 * Mock-модель сообщения: поток и каналы-проекции (§2, §6).
 *
 * Оба ключа сервер отдаёт вычисляемыми `Store.Attr`
 * (`models/mail_message.py`, `_to_store_defaults`), а не полями чтения,
 * поэтому в mock-сервере они тоже добавляются в `_to_store_defaults`.
 */
export class MailMessage extends mailModels.MailMessage {
    get _to_store_defaults() {
        return [
            ...super._to_store_defaults,
            mailDataHelpers.Store.attr(
                "stream_channel_ids",
                (message) => message.stream_channel_ids || []
            ),
            mailDataHelpers.Store.attr("streams_kind", (message) =>
                this._streams_classify(message)
            ),
        ];
    }

    /**
     * Ветка `res.partner` серверного `_message_fetch` (§18.2, Р2/Р6).
     *
     * Охват берётся ИЗ НАСТРОЕК пользователя — клиент его в запросе не
     * передаёт, поэтому и mock обязан читать `res.users.settings`, иначе
     * тест «клик по Direct перечитывает ленту» проверял бы не то.
     *
     * `thread` заменяется доменом: ядровая ветка `if (thread)` жёстко
     * сужает выборку до `model/res_id` самого треда.
     */
    _message_fetch(domain, thread, search_term, is_notification, before, after, around, limit) {
        const kwargs = getKwArgs(
            arguments,
            "domain",
            "thread",
            "search_term",
            "is_notification",
            "before",
            "after",
            "around",
            "limit"
        );
        if (kwargs.thread?._name !== "res.partner") {
            return super._message_fetch(...arguments);
        }
        const settings = this.env["res.users.settings"]._find_or_create_for_user(this.env.uid);
        const scope = settings?.streams_partner_scope || "related";
        if (scope === "direct") {
            return super._message_fetch(...arguments);
        }
        const partnerId = parseInt(kwargs.thread[0].id);
        const streamsDomain = Domain.and([
            kwargs.domain || [],
            Domain.or([
                [
                    ["model", "=", "res.partner"],
                    ["res_id", "=", partnerId],
                ],
                [["id", "in", this._streams_partner_message_ids(partnerId, scope)]],
            ]),
            [["message_type", "!=", "user_notification"]],
        ]).toList();
        return super._message_fetch(
            makeKwArgs({ ...kwargs, domain: streamsDomain, thread: undefined })
        );
    }

    /**
     * Сообщения связанных записей контакта (упрощённая SQL VIEW).
     *
     * @param {number} partnerId
     * @param {"related"|"company"} scope
     * @returns {number[]}
     */
    _streams_partner_message_ids(partnerId, scope) {
        /** @type {import("mock_models").ResPartner} */
        const ResPartner = this.env["res.partner"];

        let partnerIds = [partnerId];
        if (scope === "company") {
            const [partner] = ResPartner.browse(partnerId);
            const rootId = partner.parent_id || partnerId;
            partnerIds = [rootId, ...ResPartner.search([["parent_id", "=", rootId]])];
        }
        const ids = [];
        for (const [model, field] of STREAMS_PARTNER_SOURCES) {
            if (!this.env[model]?._fields?.[field]) {
                continue;
            }
            const resIds = this.env[model].search([[field, "in", partnerIds]]);
            if (!resIds.length) {
                continue;
            }
            ids.push(
                ...this.search([
                    ["model", "=", model],
                    ["res_id", "in", resIds],
                ])
            );
        }
        // Р7: виртуальные `change` и «прочее» в агрегат не попадают
        return ids.filter((id) => {
            const [message] = this.browse(id);
            return STREAMS_VIRTUAL_KINDS.includes(this._streams_classify(message));
        });
    }

    /**
     * Поток сообщения по подтипу и типу (упрощённый
     * `mail.message._streams_classify_vals`).
     *
     * Порядок проверок повторяет серверный: письмо — всегда внешняя
     * переписка, системный автолог без нашего подтипа — «прочее».
     *
     * @param {Object} message
     * @returns {string|false}
     */
    _streams_classify(message) {
        /** @type {import("mock_models").MailMessageSubtype} */
        const MailMessageSubtype = this.env["mail.message.subtype"];

        if (message.message_type === "user_notification") {
            return false;
        }
        if (["email", "email_outgoing"].includes(message.message_type)) {
            return "message";
        }
        const [subtype] = message.subtype_id
            ? MailMessageSubtype.browse(message.subtype_id)
            : [];
        const xmlid = subtype?.subtype_xmlid;
        if (xmlid && STREAMS_SUBTYPES[xmlid]) {
            return STREAMS_SUBTYPES[xmlid];
        }
        if (message.message_type === "notification") {
            return false;
        }
        if (xmlid === "mail.mt_note") {
            return "note";
        }
        if (xmlid === "mail.mt_comment") {
            return "comment";
        }
        return false;
    }
}
