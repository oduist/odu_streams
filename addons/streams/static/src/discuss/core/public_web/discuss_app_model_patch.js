import { fields } from "@mail/core/common/record";
import { DiscussApp } from "@mail/core/public_web/discuss_app_model";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

/** Идентификатор категории сайдбара с каналами записей. */
export const STREAMS_MESSAGES_CATEGORY_ID = "streams.messages";

patch(DiscussApp.prototype, {
    setup() {
        super.setup(...arguments);
        /**
         * Категория «Messages» — каналы записей (§11.3, A14, решение Р3).
         *
         * Ровно одна своя категория: личные Changes и Notifications
         * остаются в ядровой Channels (решение пользователя 2026-08-18).
         *
         * `sequence: 35` — сразу после ядровых Channels (10) и Direct
         * messages (30), как в клиенте 15.
         *
         * `serverStateKey` — поле `res.users.settings`
         * (`models/res_users_settings.py`); ядро сериализует все
         * неавтоматические поля настроек целиком
         * (`res.users.settings._res_users_settings_format`), поэтому
         * дополнительной серверной выдачи не требуется (проверено
         * 2026-08-19).
         */
        this.streamsRecords = fields.One("DiscussAppCategory", {
            compute() {
                return {
                    canView: false,
                    extraClass: "o-streams-DiscussSidebarCategory-messages",
                    hideWhenEmpty: true,
                    icon: "fa fa-comments-o",
                    id: STREAMS_MESSAGES_CATEGORY_ID,
                    name: _t("Messages"),
                    sequence: 35,
                    serverStateKey: "is_discuss_sidebar_category_streams_open",
                };
            },
            eager: true,
        });
    },
});
