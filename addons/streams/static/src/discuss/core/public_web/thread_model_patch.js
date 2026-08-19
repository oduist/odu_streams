import { Thread } from "@mail/core/common/thread_model";

import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    /**
     * Маршрутизация канала в категорию сайдбара (A14/A15).
     *
     * Только каналы записей уходят в нашу «Messages»; личные Changes и
     * Notifications имеют `channel_type === 'channel'` и остаются в
     * ядровой Channels (решение Р3). В 19 тред принадлежит ровно одной
     * категории — той, что вернул этот метод, поэтому «перетягивания»
     * канала двумя категориями, как в 15, здесь быть не может.
     */
    _computeDiscussAppCategory() {
        if (this.channel_kind === "record") {
            return this.store.discuss.streamsRecords;
        }
        return super._computeDiscussAppCategory();
    },
});
