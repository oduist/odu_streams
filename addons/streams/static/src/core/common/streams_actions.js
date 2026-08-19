import { _t } from "@web/core/l10n/translation";

/**
 * Действия streams, общие для чаттера записи и канала записи.
 *
 * Вынесены сюда, потому что одни и те же четыре точки входа (внешнее
 * сообщение, Notify, подписка на поля, приглашение клиента) вызываются из
 * трёх разных мест: топбар чаттера (`chatter/web/chatter_patch.js`), шапка
 * канала (`discuss/core/common/streams_thread_actions.js`) и композер
 * канала (`discuss/core/common/streams_composer_actions.js`).
 */

/**
 * Полный композер внешней переписки (§11.1, B3/C4).
 *
 * Ядро 19 понимает `default_subtype_xmlid` само: `mail.compose.message.
 * default_get` переводит его в `default_subtype_id`
 * (`mail/wizard/mail_compose_message.py`), поэтому серверного override
 * модулю не нужно (проверка S4 фазы 8, 2026-08-19).
 *
 * Осторожно: в 19 `default_res_id` в контексте композера запрещён —
 * `default_get` бросает ValueError и требует `default_res_ids`.
 *
 * @param {string} resModel модель записи-источника
 * @param {number} resId
 * @returns {Object} ir.actions.act_window
 */
export function streamsSendMessageAction(resModel, resId) {
    return {
        type: "ir.actions.act_window",
        name: _t("Send Message"),
        res_model: "mail.compose.message",
        view_mode: "form",
        views: [[false, "form"]],
        target: "new",
        context: {
            default_composition_mode: "comment",
            default_model: resModel,
            default_res_ids: [resId],
            default_subtype_xmlid: "streams.mt_message",
        },
    };
}

/**
 * Визард подписки на изменения полей записи (§8.1, B6).
 *
 * Что доступно и что предотмечено, решает сервер
 * (`wizard/streams_field_subscription_wizard.py`) — клиент передаёт только
 * модель и запись.
 */
export function streamsChangesAction(resModel, resId) {
    return {
        type: "ir.actions.act_window",
        name: _t("Changes"),
        res_model: "streams.field.subscription.wizard",
        view_mode: "form",
        views: [[false, "form"]],
        target: "new",
        context: { default_res_model: resModel, default_res_id: resId },
    };
}

/**
 * Приглашение клиента в чат записи (§9.2, B7/C2).
 *
 * Из чаттера идёт по записи (канала может ещё не быть — приглашение его
 * создаёт, пятый триггер §5.1), из канала — по `default_channel_id`.
 *
 * @param {{resModel?: string, resId?: number, channelId?: number}} params
 */
export function streamsInviteGuestAction({ resModel, resId, channelId } = {}) {
    const context = channelId
        ? { default_channel_id: channelId }
        : { default_res_model: resModel, default_res_id: resId };
    return {
        type: "ir.actions.act_window",
        name: _t("Invite a customer to this chat"),
        res_model: "streams.guest.invite.wizard",
        view_mode: "form",
        views: [[false, "form"]],
        target: "new",
        context,
    };
}

/**
 * Открыть композер уведомления (§11.1/§11.2, B5/C1).
 *
 * Сам диалог пишет пакет WP3; здесь только согласованная точка вызова —
 * метод `openNotifyComposer` сервиса `streams.core`.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {{resModel: string|false, resId: number|false, recordName?: string}} params
 */
export function streamsOpenNotifyComposer(env, params) {
    env.services["streams.core"]?.openNotifyComposer(params);
}
