import { STREAMS_MESSAGES_CATEGORY_ID } from "@streams/discuss/core/public_web/discuss_app_model_patch";

import { DiscussAppCategory } from "@mail/discuss/core/public_web/discuss_app_category_model";

import { compareDatetime } from "@mail/utils/common/misc";
import { patch } from "@web/core/utils/patch";

patch(DiscussAppCategory.prototype, {
    /**
     * Порядок каналов записей — по последней активности.
     *
     * Ядро сортирует по алфавиту только категорию Channels; наша
     * «Messages» ближе к чатам: имя канала — это имя документа, и искать
     * его глазами по алфавиту бессмысленно, а вот «где недавно писали» —
     * ровно то, что нужно. Формула взята у ядровых chats
     * (`discuss_app_category_model.js`, `sortThreads`).
     */
    sortThreads(t1, t2) {
        if (this.id === STREAMS_MESSAGES_CATEGORY_ID) {
            return compareDatetime(t2.lastInterestDt, t1.lastInterestDt) || t2.id - t1.id;
        }
        return super.sortThreads(...arguments);
    },
});
