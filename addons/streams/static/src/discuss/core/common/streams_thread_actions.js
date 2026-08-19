import {
    streamsInviteGuestAction,
    streamsOpenNotifyComposer,
} from "@streams/core/common/streams_actions";
import { StreamsFilterPanel } from "@streams/discuss/core/common/streams_filter_panel";

import { registerThreadAction } from "@mail/core/common/thread_actions";

import { _t } from "@web/core/l10n/translation";

/**
 * Шапка канала записи (§11.2) — замена `mail.thread_view_topbar` из 15.
 *
 * Общее условие всех действий: канал записи и не «мини-меню» канала в
 * сайдбаре (`isDiscussSidebarChannelActions`), где место есть только под
 * ядровые пункты.
 *
 * @param {{owner: Object, thread: import("models").Thread}} params
 */
function isStreamsRecordChannel({ owner, thread }) {
    return thread?.channel_kind === "record" && !owner.isDiscussSidebarChannelActions;
}

registerThreadAction("streams-filters", {
    actionPanelComponent: StreamsFilterPanel,
    actionPanelComponentProps: ({ thread }) => ({ thread }),
    condition: isStreamsRecordChannel,
    icon: "fa fa-fw fa-filter",
    name: _t("Streams"),
    panelOuterClass: "o-streams-FilterPanel bg-inherit",
    sequence: 25,
    sequenceGroup: 20,
    toggle: true,
});

registerThreadAction("streams-notify", {
    condition: isStreamsRecordChannel,
    icon: "fa fa-fw fa-bell-o",
    name: _t("Notify"),
    open: ({ owner, thread }) =>
        streamsOpenNotifyComposer(owner.env, {
            // запись-источник канала, а не сам канал: уведомление всегда
            // ссылается на документ (§12.2)
            resModel: thread.res_model,
            resId: thread.res_id,
            recordName: thread.displayName,
        }),
    sequence: 26,
    sequenceGroup: 20,
});

registerThreadAction("streams-invite-guest", {
    condition: isStreamsRecordChannel,
    icon: "fa fa-fw fa-user-plus",
    name: _t("Invite customer"),
    open: ({ owner, thread }) =>
        owner.env.services.action.doAction(streamsInviteGuestAction({ channelId: thread.id })),
    sequence: 27,
    sequenceGroup: 20,
});

registerThreadAction("streams-schedule-activity", {
    condition: (params) =>
        isStreamsRecordChannel(params) && params.thread.res_model && params.thread.res_id,
    icon: "fa fa-fw fa-clock-o",
    name: _t("Schedule activity"),
    /**
     * Планировщик активностей для записи-источника канала (C5).
     *
     * Зовём ядровый `store.scheduleActivity`
     * (`mail/static/src/core/web/store_service_patch.js`): он открывает
     * `mail.activity.schedule` с контекстом `active_model`/`active_ids`/
     * `active_id` и дожидается закрытия. Своё act_window писать не надо —
     * контекстные ключи планировщика могут поменяться, а метод ядра нет.
     */
    open: async ({ store, thread }) => {
        await store.scheduleActivity(thread.res_model, [thread.res_id]);
        // активность рождает синтетическое сообщение потока `activity`
        // (`models/mail_activity.py`) — оно приезжает только перечиткой
        await thread.fetchNewMessages();
    },
    sequence: 28,
    sequenceGroup: 20,
});
