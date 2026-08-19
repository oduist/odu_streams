import { mailDataHelpers } from "@mail/../tests/mock_server/mail_mock_server";

import {
    Command,
    fields,
    getKwArgs,
    models,
    serverState,
} from "@web/../tests/web_test_helpers";
import { serializeDateTime } from "@web/core/l10n/dates";

const { DateTime } = luxon;

/** Типы шины подсистемы Notify (`models/mail_notify.py`). */
export const BUS_NEW = "streams.notify/new";
export const BUS_UPDATE = "streams.notify/update";
export const BUS_COUNTER = "streams.notify/counter";

/** Дефолт таймаута попапа; на сервере — системный параметр (§14). */
export const DEFAULT_NOTIFY_TIMEOUT = 10;

/**
 * Mock-модель приоритетного уведомления (§12).
 *
 * Уведомление — не `mail.message`, поэтому и в mock-сервере у него своя
 * модель со своим payload'ом: `_streams_payload` — общая форма элемента
 * лент Received/Sent и payload'ов шины `streams.notify/new|update`.
 * Поля подтягиваются с живого сервера (`models.ServerModel`); руками
 * задаются только дефолты — `fields_get` их не отдаёт.
 */
export class MailNotify extends models.ServerModel {
    _name = "mail.notify";

    author_id = fields.Generic({ default: () => serverState.userId });
    is_sticky = fields.Generic({ default: false });
    timeout = fields.Generic({ default: DEFAULT_NOTIFY_TIMEOUT });
    transcript_state = fields.Generic({ default: "none" });

    /**
     * Общая форма элемента ленты; она же payload шины.
     *
     * @param {number} id
     * @param {Object} [recipient] строка получателя (вкладка Received)
     * @param {boolean} [with_recipients] отметки доставки (вкладка Sent)
     */
    _streams_payload(id, recipient, with_recipients) {
        const kwargs = getKwArgs(arguments, "id", "recipient", "with_recipients");
        id = kwargs.id;
        recipient = kwargs.recipient;
        with_recipients = kwargs.with_recipients;

        /** @type {import("mock_models").IrAttachment} */
        const IrAttachment = this.env["ir.attachment"];
        /** @type {import("mock_models").MailNotifyRecipient} */
        const MailNotifyRecipient = this.env["mail.notify.recipient"];
        /** @type {import("mock_models").ResUsers} */
        const ResUsers = this.env["res.users"];

        const [notify] = this.browse(id);
        const [author] = ResUsers.browse(notify.author_id);
        const [voiceAttachment] = notify.voice_attachment_id
            ? IrAttachment.browse(notify.voice_attachment_id)
            : [];
        const payload = {
            id: notify.id,
            date: notify.create_date || serializeDateTime(DateTime.now()),
            author: { id: author?.id || false, name: author?.name || "" },
            body: notify.body || "",
            is_sticky: Boolean(notify.is_sticky),
            timeout: notify.timeout || DEFAULT_NOTIFY_TIMEOUT,
            res_model: notify.res_model || false,
            res_id: notify.res_id || false,
            record_name: notify.record_name || "",
            attachments: IrAttachment.browse(notify.attachment_ids || [])
                .filter((attachment) => attachment.id !== voiceAttachment?.id)
                .map((attachment) => ({
                    id: attachment.id,
                    name: attachment.name,
                    mimetype: attachment.mimetype || "",
                    size: attachment.file_size || 0,
                })),
            voice: voiceAttachment
                ? {
                      id: voiceAttachment.id,
                      mimetype: voiceAttachment.mimetype || "",
                      duration: notify.voice_duration || 0,
                  }
                : false,
            transcript: notify.transcript || false,
            transcript_state: notify.transcript_state,
            parent_id: notify.parent_id || false,
        };
        if (recipient) {
            payload.read_date = recipient.read_date || false;
            payload.popup_shown = Boolean(recipient.popup_shown);
        }
        if (with_recipients) {
            payload.recipients = MailNotifyRecipient.browse(notify.recipient_ids || []).map(
                (row) => {
                    const [user] = ResUsers.browse(row.user_id);
                    return {
                        user_id: row.user_id,
                        name: user?.name || "",
                        read_date: row.read_date || false,
                    };
                }
            );
        }
        return payload;
    }

    /** @param {Object} vals значения формы композера (§12.2) */
    streams_notify_send(vals) {
        const kwargs = getKwArgs(arguments, "vals");
        vals = kwargs.vals || {};
        return { id: this._streams_create(vals) };
    }

    /**
     * Ответ на уведомление (§12.6): получателя выбирает сервер — им
     * всегда становится автор родителя.
     *
     * @param {number} parent_id
     * @param {Object} vals
     */
    streams_notify_reply(parent_id, vals) {
        const kwargs = getKwArgs(arguments, "parent_id", "vals");
        parent_id = kwargs.parent_id;
        vals = { ...(kwargs.vals || {}) };
        const [parent] = this.browse(parent_id);
        vals.user_ids = [parent.author_id];
        vals.is_sticky = vals.is_sticky ?? parent.is_sticky;
        vals.timeout = vals.timeout ?? parent.timeout;
        return { id: this._streams_create(vals, parent_id) };
    }

    /**
     * @param {Object} vals
     * @param {number} [parentId]
     * @returns {number} id созданного уведомления
     */
    _streams_create(vals, parentId) {
        /** @type {import("mock_models").BusBus} */
        const BusBus = this.env["bus.bus"];
        /** @type {import("mock_models").ResPartner} */
        const ResPartner = this.env["res.partner"];
        /** @type {import("mock_models").ResUsers} */
        const ResUsers = this.env["res.users"];

        const userIds = vals.user_ids || [];
        const notifyId = this.create({
            body: vals.body ? `<p>${vals.body}</p>` : "",
            attachment_ids: vals.attachment_ids || [],
            voice_attachment_id: vals.voice_attachment_id || false,
            voice_duration: vals.voice_duration || 0,
            is_sticky: Boolean(vals.is_sticky),
            timeout: vals.timeout || DEFAULT_NOTIFY_TIMEOUT,
            res_model: vals.res_model || false,
            res_id: vals.res_id || false,
            record_name: vals.record_name || "",
            parent_id: parentId || false,
            recipient_ids: userIds.map((userId) => Command.create({ user_id: userId })),
        });
        // рассылка адресная: каждому получателю на его партнёрский канал
        for (const userId of userIds) {
            const [user] = ResUsers.browse(userId);
            const [partner] = ResPartner.browse(user.partner_id);
            BusBus._sendone(partner, BUS_NEW, {
                ...this._streams_payload(notifyId),
                counter: this._streams_notify_counter(userId),
            });
        }
        return notifyId;
    }

    /**
     * @param {string} [box] "received" | "sent"
     * @param {number} [limit]
     * @param {number} [before_id]
     */
    streams_notify_feed(box, limit, before_id) {
        const kwargs = getKwArgs(arguments, "box", "limit", "before_id");
        box = kwargs.box || "received";
        limit = kwargs.limit || 30;
        before_id = kwargs.before_id;

        /** @type {import("mock_models").MailNotifyRecipient} */
        const MailNotifyRecipient = this.env["mail.notify.recipient"];

        const domain = [];
        if (box === "sent") {
            domain.push(["author_id", "=", this.env.uid]);
        } else {
            const rows = MailNotifyRecipient._filter([["user_id", "=", this.env.uid]]);
            domain.push(["id", "in", rows.map((row) => row.notify_id)]);
        }
        if (before_id) {
            domain.push(["id", "<", before_id]);
        }
        // лента идёт от самого свежего (`_order = 'id desc'`)
        const ids = this.search(domain)
            .sort((a, b) => b - a)
            .slice(0, limit);
        return ids.map((id) => {
            if (box === "sent") {
                return this._streams_payload(id, undefined, true);
            }
            const [row] = MailNotifyRecipient._filter([
                ["notify_id", "=", id],
                ["user_id", "=", this.env.uid],
            ]);
            return this._streams_payload(id, row);
        });
    }

    /** @param {number} [userId] */
    _streams_notify_counter(userId) {
        /** @type {import("mock_models").MailNotifyRecipient} */
        const MailNotifyRecipient = this.env["mail.notify.recipient"];

        return MailNotifyRecipient._filter([
            ["user_id", "=", userId ?? this.env.uid],
            ["read_date", "=", false],
        ]).length;
    }

    /** @param {number[]} notify_ids */
    streams_notify_mark_read(notify_ids) {
        const kwargs = getKwArgs(arguments, "notify_ids");
        notify_ids = kwargs.notify_ids || [];

        /** @type {import("mock_models").MailNotifyRecipient} */
        const MailNotifyRecipient = this.env["mail.notify.recipient"];

        const rows = MailNotifyRecipient._filter([
            ["notify_id", "in", notify_ids],
            ["user_id", "=", this.env.uid],
            ["read_date", "=", false],
        ]);
        if (rows.length) {
            MailNotifyRecipient.write(
                rows.map((row) => row.id),
                { read_date: serializeDateTime(DateTime.now()) }
            );
        }
        return { counter: this._streams_notify_counter() };
    }

    /** @param {number[]} notify_ids */
    streams_notify_popup_shown(notify_ids) {
        const kwargs = getKwArgs(arguments, "notify_ids");
        notify_ids = kwargs.notify_ids || [];

        /** @type {import("mock_models").MailNotifyRecipient} */
        const MailNotifyRecipient = this.env["mail.notify.recipient"];

        const rows = MailNotifyRecipient._filter([
            ["notify_id", "in", notify_ids],
            ["user_id", "=", this.env.uid],
        ]);
        if (rows.length) {
            MailNotifyRecipient.write(
                rows.map((row) => row.id),
                { popup_shown: true }
            );
        }
        return true;
    }

    /**
     * Личный канал Notifications, создавая его при первом заходе (S3).
     *
     * Контракт с клиентом: id канала плюс Store-payload его данных — из
     * него канал появляется в сайдбаре без отдельной перезагрузки.
     */
    streams_notify_open_channel() {
        /** @type {import("mock_models").DiscussChannel} */
        const DiscussChannel = this.env["discuss.channel"];

        let [channel] = DiscussChannel._filter([
            ["channel_kind", "=", "notifications"],
            ["owner_user_id", "=", this.env.uid],
        ]);
        if (!channel) {
            const channelId = DiscussChannel.create({
                name: "Notifications",
                channel_type: "channel",
                channel_kind: "notifications",
                owner_user_id: this.env.uid,
                channel_member_ids: [Command.create({ partner_id: this.env.user.partner_id })],
            });
            [channel] = DiscussChannel.browse(channelId);
        }
        return {
            channel_id: channel.id,
            data: new mailDataHelpers.Store()
                .add(DiscussChannel.browse(channel.id))
                .get_result(),
        };
    }

    /** Стартовый payload подсистемы (E1): счётчик, канал, попапы. */
    _streams_init_messaging() {
        /** @type {import("mock_models").DiscussChannel} */
        const DiscussChannel = this.env["discuss.channel"];
        /** @type {import("mock_models").MailNotifyRecipient} */
        const MailNotifyRecipient = this.env["mail.notify.recipient"];

        const [channel] = DiscussChannel._filter([
            ["channel_kind", "=", "notifications"],
            ["owner_user_id", "=", this.env.uid],
        ]);
        const rows = MailNotifyRecipient._filter([
            ["user_id", "=", this.env.uid],
            ["popup_shown", "=", false],
        ]);
        return {
            counter: this._streams_notify_counter(),
            channel_id: channel?.id || false,
            default_timeout: DEFAULT_NOTIFY_TIMEOUT,
            pending: rows.map((row) => this._streams_payload(row.notify_id, row)),
        };
    }
}
