import { mailModels } from "@mail/../tests/mail_test_helpers";

import { getKwArgs } from "@web/../tests/web_test_helpers";

/**
 * Дефолты фильтров отображения потоков.
 *
 * Дубль серверных `STREAMS_FILTER_DEFAULTS` (`models/mail_message.py`) и
 * клиентских (`core/common/thread_model_patch.js`): mock-сервер обязан
 * отдавать ровно то же, что настоящий, иначе тест панели фильтров будет
 * зелёным на неверном контракте.
 */
export const STREAMS_FILTER_DEFAULTS = {
    activity: true,
    change: false,
    comment: true,
    message: true,
    note: true,
};

/**
 * Mock-модель канала (§5, §6, §8.3).
 *
 * Поля `channel_kind`/`res_model`/`res_id`/`streams_filters` в описании
 * модели появляются сами: ядровая `DiscussChannel` — `models.ServerModel`,
 * и её поля подтягиваются с живого сервера, где streams установлен.
 * Руками добавляется только то, чего в схеме нет: выдача этих полей
 * клиенту (`_to_store`) и наши RPC.
 */
export class DiscussChannel extends mailModels.DiscussChannel {
    /** Вид канала и его запись-источник нужны клиенту всегда (§11.3). */
    _channel_basic_info_fields() {
        return [...super._channel_basic_info_fields(), "channel_kind", "res_id", "res_model"];
    }

    /** @param {number[]} ids */
    _to_store(store, fields) {
        const kwargs = getKwArgs(arguments, "store", "fields");
        store = kwargs.store;
        fields = kwargs.fields;
        super._to_store(...arguments);
        if (fields && Array.isArray(fields) && fields.length) {
            // точечная выдача конкретных полей — фильтры туда не входят
            return;
        }
        for (const channel of this) {
            // персональные фильтры отдаются только их владельцу
            const member = this._find_or_create_member_for_self(channel.id);
            store._add_record_fields(this.browse(channel.id), {
                streams_filters: this._streams_get_filters(member?.id),
            });
        }
    }

    /**
     * Фильтры участника поверх дефолтов; хранятся JSON-строкой, как на
     * сервере (`discuss.channel.member.streams_filters`).
     *
     * @param {number} [memberId]
     * @returns {Object<string, boolean>}
     */
    _streams_get_filters(memberId) {
        /** @type {import("mock_models").DiscussChannelMember} */
        const DiscussChannelMember = this.env["discuss.channel.member"];

        const filters = { ...STREAMS_FILTER_DEFAULTS };
        if (!memberId) {
            return filters;
        }
        const [member] = DiscussChannelMember.browse(memberId);
        let stored;
        try {
            stored = JSON.parse(member?.streams_filters || "{}");
        } catch {
            stored = {};
        }
        for (const [key, value] of Object.entries(stored || {})) {
            if (key in filters) {
                filters[key] = Boolean(value);
            }
        }
        return filters;
    }

    /**
     * @param {number[]} ids
     * @param {Object<string, boolean>} filters
     */
    streams_set_filters(ids, filters) {
        const kwargs = getKwArgs(arguments, "ids", "filters");
        ids = kwargs.ids;
        filters = kwargs.filters || {};

        /** @type {import("mock_models").DiscussChannelMember} */
        const DiscussChannelMember = this.env["discuss.channel.member"];

        const member = this._find_or_create_member_for_self(ids[0]);
        if (!member) {
            return false;
        }
        const current = this._streams_get_filters(member.id);
        for (const [key, value] of Object.entries(filters)) {
            if (key in STREAMS_FILTER_DEFAULTS) {
                current[key] = Boolean(value);
            }
        }
        DiscussChannelMember.write([member.id], {
            streams_filters: JSON.stringify(current),
        });
        return current;
    }

    /**
     * Отметка прочтения лент Changes/Notifications (решение Р4 фазы 8).
     *
     * @param {number[]} ids
     * @param {number} last_message_id
     */
    streams_mark_read(ids, last_message_id) {
        const kwargs = getKwArgs(arguments, "ids", "last_message_id");
        ids = kwargs.ids;
        last_message_id = parseInt(kwargs.last_message_id || 0, 10);

        /** @type {import("mock_models").DiscussChannelMember} */
        const DiscussChannelMember = this.env["discuss.channel.member"];

        if (!last_message_id) {
            return false;
        }
        const member = this._find_or_create_member_for_self(ids[0]);
        if (!member) {
            return false;
        }
        // `seen_message_id` намеренно не трогаем: это m2o на `mail.message`,
        // а ленты Changes/Notify отмечают прочтение по id сообщений, записей
        // которых в mock-сервере может и не быть
        DiscussChannelMember.write([member.id], {
            new_message_separator: last_message_id + 1,
            message_unread_counter: 0,
        });
        return { unread: 0 };
    }

    /**
     * Лента личного канала Changes (§8.3).
     *
     * Полноценной выборки здесь нет намеренно: элемент ленты сервер
     * собирает из сообщений, подписки на поля и прав на запись — три
     * подсистемы, которых в mock-сервере нет вовсе. Тесты ленты подменяют
     * ответ через `onRpc`; этот дефолт нужен, чтобы канал Changes,
     * открытый в любом другом тесте, не ронял RPC-заглушкой.
     *
     * @param {number[]} ids
     * @param {number} [limit]
     * @param {number} [before_id]
     * @param {boolean} [with_cursor]
     */
    streams_changes_feed(ids, limit, before_id, with_cursor) {
        const kwargs = getKwArgs(arguments, "ids", "limit", "before_id", "with_cursor");
        with_cursor = kwargs.with_cursor;
        return with_cursor ? { items: [], cursor: null, has_more: false } : [];
    }
}
