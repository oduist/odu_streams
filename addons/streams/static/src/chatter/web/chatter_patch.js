import {
    streamsChangesAction,
    streamsInviteGuestAction,
    streamsOpenNotifyComposer,
    streamsSendMessageAction,
} from "@streams/core/common/streams_actions";

import {
    STREAMS_PARTNER_SCOPE_DEFAULT,
    STREAMS_PARTNER_SCOPES,
} from "@streams/core/common/settings_model_patch";

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

    // ------------------------------------------------------------
    // ОХВАТ ЧАТТЕРА КОНТАКТА (§18.2)
    // ------------------------------------------------------------

    /**
     * Показывать ли сегмент охвата.
     *
     * Только чаттер сохранённой карточки контакта: агрегат живёт в
     * серверной ветке `_message_fetch` для `thread._name == 'res.partner'`,
     * а до сохранения у треда нет id и запрашивать нечего.
     */
    get streamsShowsPartnerScope() {
        const thread = this.state.thread;
        return Boolean(thread && thread.model === "res.partner" && thread.id);
    },

    /**
     * Текущий охват.
     *
     * Фолбэк на дефолт нужен не для красоты: до прихода
     * `res.users.settings` (и у пользователя без записи настроек)
     * ключа в объекте нет, а сервер в этом случае читает `related`.
     */
    get streamsPartnerScope() {
        return this.store.settings?.streams_partner_scope || STREAMS_PARTNER_SCOPE_DEFAULT;
    },

    /**
     * Доступные охваты (Р11).
     *
     * Company прячется у контакта без организации и без дочерних
     * контактов: там этот уровень совпадает с Related и только путает.
     */
    get streamsPartnerScopes() {
        const available = this.state.thread?.streams_company_scope_available;
        return STREAMS_PARTNER_SCOPES.filter(
            (item) => item.scope !== "company" || available
        );
    },

    /**
     * Переключить охват и перечитать ленту.
     *
     * Охват — персистентная настройка пользователя, и клиент его в
     * запросе ленты НЕ передаёт (Р6): сервер читает настройку сам.
     * Поэтому одного оптимистичного апдейта мало — после сохранения
     * лента перечитывается целиком (`loadAround`, см.
     * `core/common/thread_model_patch.js`).
     *
     * @param {"direct"|"related"|"company"} scope
     */
    async onClickStreamsPartnerScope(scope) {
        const thread = this.state.thread;
        const settings = this.store.settings;
        const previous = this.streamsPartnerScope;
        if (!thread?.id || scope === previous) {
            return;
        }
        // оптимистично: сегмент должен отзываться мгновенно
        settings.streams_partner_scope = scope;
        if (settings.id) {
            try {
                await this.env.services.orm.call(
                    "res.users.settings",
                    "set_res_users_settings",
                    [[settings.id]],
                    { new_settings: { streams_partner_scope: scope } }
                );
            } catch (error) {
                settings.streams_partner_scope = previous;
                throw error;
            }
        }
        await thread.streamsReloadMessages();
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
