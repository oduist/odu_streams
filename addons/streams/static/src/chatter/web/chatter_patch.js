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
 * Порядок применения патчей: НАШ идёт последним.
 *
 * Класс `Chatter` объявлен в `@mail/chatter/web_portal/chatter`, но всё
 * поведение чаттера записи ядро добавляет отдельным патчем —
 * `@mail/chatter/web/chatter_patch`. Импорта самого класса недостаточно:
 * загрузчик Odoo выполняет модуль, как только готовы ЕГО зависимости, а у
 * ядрового патча их много (Activity, ScheduledMessage, RecipientsInput…),
 * поэтому он выполняется ПОЗЖЕ нас. `patch` же оставляет в живых
 * последнего: ядровые `toggleComposer` и `onClickSearch` не зовут
 * `super`, так что наши одноимённые методы молча переставали вызываться
 * (композер закрывался после отправки).
 *
 * Побочный импорт — ядровая идиома ровно для этого случая
 * (`mail/chatter/web/thread_model_patch.js`, `crm_livechat/.../thread_actions.js`).
 */
import "@mail/chatter/web/chatter_patch";

/**
 * Кнопки чаттера записи (§11.1, редизайн топбара фазой 9.5).
 *
 * Ядровые Send message / Log note скрыты в шаблоне (`chatter_patch.xml`):
 * их единственной работой было открыть композер, а он теперь открыт
 * всегда. Отправка комментарием и заметкой переехала в футер композера —
 * кнопки Send (ядровая) и Note (наша, `core/common/composer_patch.*`).
 * Топбар записи: Message · Notify · Changes · Invite.
 */
patch(Chatter.prototype, {
    // ------------------------------------------------------------
    // ВСЕГДА ОТКРЫТЫЙ КОМПОЗЕР (решение пользователя 2026-08-19)
    // ------------------------------------------------------------

    /**
     * Держать ли композер этого чаттера открытым.
     *
     * Условие — сохранённая запись, и берётся оно из треда, а не из
     * `props.threadId`: `changeThread` вызывается из `onWillUpdateProps`,
     * когда `this.props` ещё старые. У несохранённой записи тред
     * транзиентный (без id), отправлять в него нечего, а ядровый путь
     * «открыть композер → `saveRecord`» (`toggleComposer`) мы оставляем
     * ядру нетронутым.
     */
    get streamsKeepsComposerOpen() {
        return Boolean(this.state.thread?.id);
    },

    /** Режим всегда открытого композера — внутренний комментарий. */
    get streamsDefaultComposerType() {
        return "message";
    },

    /**
     * Открыть композер сразу, как только у треда появился id.
     *
     * `changeThread` — единственная точка входа: её зовут и `_onMounted`,
     * и `onWillUpdateProps` при смене записи. Ядро в этом же методе
     * обнуляет `composerType` для `threadId === false` — эту ветку не
     * трогаем.
     */
    changeThread(threadModel, threadId) {
        super.changeThread(...arguments);
        if (this.streamsKeepsComposerOpen) {
            this.state.composerType = this.streamsDefaultComposerType;
        }
    },

    /**
     * Композер чаттера записи не закрывается.
     *
     * Ядро зовёт `toggleComposer()` без аргументов там, где раньше это
     * значило «закрыть»: после отправки (`onPostCallback`) и после
     * закрытия полного композера (`onCloseFullComposerCallback`). У нас
     * это «вернуться в режим комментария». `force` обязателен: без него
     * повторный вызов с текущим режимом закрыл бы композер (ядро
     * трактует его как тумблер).
     *
     * Режим `note` сюда приходит от ядрового message action «Reply»
     * (`mail/static/src/core/common/message_actions.js`) — его сохраняем
     * как есть, до следующей отправки.
     */
    toggleComposer(mode = false, options = {}) {
        if (!this.streamsKeepsComposerOpen) {
            return super.toggleComposer(...arguments);
        }
        return super.toggleComposer(mode || this.streamsDefaultComposerType, {
            ...options,
            force: true,
        });
    },

    /**
     * Поиск по сообщениям прячет композер — вернуть его при закрытии.
     *
     * Ядро гасит `composerType` прямо в `onClickSearch`, а закрыть поиск
     * можно ещё и крестиком внутри `SearchMessageInput` (`closeSearch`).
     * Патчим обе точки, иначе композер исчезает навсегда.
     */
    onClickSearch() {
        super.onClickSearch(...arguments);
        if (!this.state.isSearchOpen && this.streamsKeepsComposerOpen) {
            this.state.composerType = this.streamsDefaultComposerType;
        }
    },

    closeSearch() {
        super.closeSearch(...arguments);
        if (!this.state.composerType && this.streamsKeepsComposerOpen) {
            this.state.composerType = this.streamsDefaultComposerType;
        }
    },

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
