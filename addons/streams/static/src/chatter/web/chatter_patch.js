import {
    streamsChangesAction,
    streamsInviteGuestAction,
    streamsOpenNotifyComposer,
    streamsSendMessageAction,
} from "@streams/core/common/streams_actions";

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { patch } from "@web/core/utils/patch";

/**
 * Кнопки чаттера записи (§11.1).
 *
 * Ядровые Send message / Log note переименованы в шаблоне
 * (`chatter_patch.xml`) — классы `o-mail-Chatter-sendMessage` и
 * `o-mail-Chatter-logNote` сохранены: на них опираются тесты ядра и
 * сторонние модули. Их поведение не меняется: Comment — это ядровый
 * композер `type='message'` (подтип `mail.mt_comment`), Note — ядровый
 * `type='note'`. Внешняя переписка ушла в отдельную кнопку Send Message
 * (решение Р2 фазы 8).
 */
patch(Chatter.prototype, {
    /**
     * Показывать ли строку получателей «To: …» над композером.
     *
     * Для записей streams — никогда: внутренний комментарий писем не
     * рассылает (инвариант модуля), а список получателей над ним
     * обещает обратное. Внешняя переписка идёт полным композером.
     *
     * Предикат один на весь модуль — тот же, которым
     * `store_service_patch.js` глушит подмешивание получателей в
     * `partner_ids`, чтобы UI и отправка не разъезжались.
     */
    get streamsShowsRecipients() {
        const thread = this.state.thread;
        return !thread || !this.store.streamsSuppressesRecipients(thread);
    },

    /** Внешняя переписка: полный композер с подтипом `streams.mt_message`. */
    onClickStreamsSendMessage() {
        const thread = this.state.thread;
        if (!thread?.id) {
            return;
        }
        this.env.services.action.doAction(
            streamsSendMessageAction(this.props.threadModel, this.props.threadId),
            {
                onClose: () => {
                    // сообщение уходит мимо клиентского Store — лента
                    // чаттера о нём узнает только перечиткой
                    this.load(this.state.thread, this.onCloseFullComposerRequestList);
                },
            }
        );
    },

    /** Приоритетное уведомление по записи (§12.2). */
    onClickStreamsNotify() {
        const thread = this.state.thread;
        if (!thread?.id) {
            return;
        }
        streamsOpenNotifyComposer(this.env, {
            resModel: this.props.threadModel,
            resId: this.props.threadId,
            recordName: thread.displayName,
        });
    },

    /** Подписка на изменения полей записи (§8.1). */
    onClickStreamsChanges() {
        if (!this.state.thread?.id) {
            return;
        }
        this.env.services.action.doAction(
            streamsChangesAction(this.props.threadModel, this.props.threadId)
        );
    },

    /**
     * Приглашение клиента (§9.2).
     *
     * Кнопка есть и на записях без канала: канал создаёт сам визард,
     * поэтому спрашивать сервер о наличии канала на каждой форме не надо.
     */
    onClickStreamsInvite() {
        if (!this.state.thread?.id) {
            return;
        }
        this.env.services.action.doAction(
            streamsInviteGuestAction({
                resModel: this.props.threadModel,
                resId: this.props.threadId,
            })
        );
    },
});
