import { mailModels } from "@mail/../tests/mail_test_helpers";

import {
    Command,
    defineModels,
    defineParams,
    serverState,
} from "@web/../tests/web_test_helpers";

import { DiscussChannel } from "./mock_server/mock_models/discuss_channel";
import { MailMessage } from "./mock_server/mock_models/mail_message";
import { MailThread } from "./mock_server/mock_models/mail_thread";
import { MailNotify } from "./mock_server/mock_models/mail_notify";
import { MailNotifyRecipient } from "./mock_server/mock_models/mail_notify_recipient";
import { ResUsers } from "./mock_server/mock_models/res_users";
import { ResUsersSettings } from "./mock_server/mock_models/res_users_settings";

export { STREAMS_FILTER_DEFAULTS } from "./mock_server/mock_models/discuss_channel";
export { BUS_COUNTER, BUS_NEW, BUS_UPDATE } from "./mock_server/mock_models/mail_notify";

/**
 * Mock-модели streams: свои (`mail.notify`, `mail.notify.recipient`) плюс
 * подклассы ядровых.
 *
 * Ядровой набор раскрывается здесь же и наши классы ложатся поверх него ПО
 * КЛЮЧУ объекта (`DiscussChannel`, `MailMessage`, ...) — так же, как это
 * делает `im_livechat` (`livechat_test_helpers.js`). Это не косметика:
 * `defineModels` получает `Object.values()`, и если ядровый класс и наш
 * подкласс попадут в набор ОБА (например, из-за отдельного вызова
 * `defineMailModels()`), `MockServer._loadModels` увидит две модели с одним
 * `_name` и сделает
 * `Object.setPrototypeOf(Object.getPrototypeOf(model), existingModel)`.
 * Для подкласса `Object.getPrototypeOf(model)` — это и есть ядровый класс,
 * то есть прототип замкнётся сам на себя: `TypeError: Cyclic __proto__
 * value`, и падает весь набор. Поэтому набор регистрируется РОВНО ОДИН РАЗ
 * и только через `defineStreamsModels()`.
 */
export const streamsModels = {
    ...mailModels,
    DiscussChannel,
    MailMessage,
    MailThread,
    MailNotify,
    MailNotifyRecipient,
    ResUsers,
    ResUsersSettings,
};

/**
 * Регистрация mock-моделей streams.
 *
 * Заменяет собой `defineMailModels()` (в том числе его
 * `defineParams({suite: "mail"})`) — вызывать оба нельзя, см. комментарий
 * к `streamsModels`.
 */
export function defineStreamsModels() {
    defineParams({ suite: "mail" }, "replace");
    return defineModels(streamsModels);
}

/**
 * Канал записи (§5): зеркало чаттера конкретного документа.
 *
 * @param {Object} pyEnv
 * @param {Object} params
 * @param {string} params.resModel модель записи-источника
 * @param {number} params.resId
 * @param {string} params.name имя канала (совпадает с именем документа)
 * @param {Object} [params.values] дополнительные значения канала
 * @returns {number} id канала
 */
export function createStreamsRecordChannel(pyEnv, { resModel, resId, name, values = {} }) {
    return pyEnv["discuss.channel"].create({
        name,
        channel_type: "channel",
        channel_kind: "record",
        res_model: resModel,
        res_id: resId,
        channel_member_ids: [Command.create({ partner_id: serverState.partnerId })],
        ...values,
    });
}

/**
 * Личный служебный канал (§8.3, §12.5).
 *
 * @param {Object} pyEnv
 * @param {"changes"|"notifications"} kind
 * @returns {number} id канала
 */
export function createStreamsPersonalChannel(pyEnv, kind) {
    return pyEnv["discuss.channel"].create({
        name: kind === "changes" ? "Changes" : "Notifications",
        channel_type: "channel",
        channel_kind: kind,
        owner_user_id: serverState.userId,
        channel_member_ids: [Command.create({ partner_id: serverState.partnerId })],
    });
}
