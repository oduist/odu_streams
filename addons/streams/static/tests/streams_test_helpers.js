import { mailModels } from "@mail/../tests/mail_test_helpers";

import { Command, defineModels, serverState } from "@web/../tests/web_test_helpers";

import { DiscussChannel } from "./mock_server/mock_models/discuss_channel";
import { MailMessage } from "./mock_server/mock_models/mail_message";
import { MailNotify } from "./mock_server/mock_models/mail_notify";
import { MailNotifyRecipient } from "./mock_server/mock_models/mail_notify_recipient";
import { ResUsers } from "./mock_server/mock_models/res_users";
import { ResUsersSettings } from "./mock_server/mock_models/res_users_settings";

export { STREAMS_FILTER_DEFAULTS } from "./mock_server/mock_models/discuss_channel";
export { BUS_COUNTER, BUS_NEW, BUS_UPDATE } from "./mock_server/mock_models/mail_notify";

/**
 * Mock-модели streams: свои (`mail.notify`, `mail.notify.recipient`) плюс
 * подклассы ядровых. Ядровые перечислены здесь же, потому что mock-сервер
 * регистрирует модели по `_name` и побеждает последняя регистрация —
 * набор должен быть цельным.
 */
export const streamsModels = {
    ...mailModels,
    DiscussChannel,
    MailMessage,
    MailNotify,
    MailNotifyRecipient,
    ResUsers,
    ResUsersSettings,
};

/**
 * Регистрация mock-моделей streams.
 *
 * Вызывается в тестовом файле сразу после `defineMailModels()`: ядровый
 * набор задаёт базу (в том числе `defineParams({suite: "mail"})`), наш —
 * переопределяет то, что расширяет streams.
 */
export function defineStreamsModels() {
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
