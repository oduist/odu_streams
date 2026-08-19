import { Thread } from "@mail/core/common/thread";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

/**
 * Ссылка на запись под приветствием канала (§11.2).
 *
 * Ядро пишет в начале ленты «This is the start of the #<канал> channel»,
 * и на этом след документа обрывается: имя канала — не ссылка. Для канала
 * записи это единственное место, где видно, ЧЕЙ это канал, поэтому сразу
 * под фразой ставится переход к самой записи. Второй путь — пункт
 * «Open Record» в шапке канала и в мини-меню сайдбара
 * (`discuss/core/common/streams_thread_actions.js`).
 */
patch(Thread.prototype, {
    /**
     * Подпись ссылки или `false`, если тред — не канал записи.
     *
     * Имя записи берётся у канала: канал записи назван документом и
     * переименовывается вместе с ним (`models/mail_thread.py`).
     *
     * @returns {string|false}
     */
    get streamsRecordLinkLabel() {
        const thread = this.props.thread;
        if (thread?.channel_kind !== "record" || !thread.res_model || !thread.res_id) {
            return false;
        }
        return _t("Open %(record_name)s", { record_name: thread.displayName });
    },

    /** Открыть запись-источник канала. */
    streamsOpenRecord() {
        const thread = this.props.thread;
        this.store.openDocument({ model: thread.res_model, id: thread.res_id });
    },
});
