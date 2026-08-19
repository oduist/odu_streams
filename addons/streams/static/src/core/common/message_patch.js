import { Message } from "@mail/core/common/message";
import { patch } from "@web/core/utils/patch";

patch(Message.prototype, {
    /**
     * Ссылка «on <документ>» в ленте канала записи (A8).
     *
     * Канал записи и есть этот документ, поэтому подпись под каждым
     * сообщением бессмысленна. В Inbox, Starred и любых других проекциях
     * ссылка остаётся — там она единственный ориентир.
     *
     * Правится геттер, а не шаблон: в 19 условие целиком вычисляется в
     * компоненте (`mail/static/src/core/common/message.js`,
     * `isPersistentMessageFromAnotherThread`), а `<small>` в `message.xml`
     * не имеет ни класса, ни имени — xpath по нему был бы заметно
     * хрупче (риск 6 отчёта core).
     */
    get isPersistentMessageFromAnotherThread() {
        const thread = this.props.thread;
        const origin = this.message.thread;
        if (
            thread?.channel_kind === "record" &&
            origin &&
            origin.model === thread.res_model &&
            origin.id === thread.res_id
        ) {
            return false;
        }
        return super.isPersistentMessageFromAnotherThread;
    },
});
