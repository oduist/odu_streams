# Фаза 8 — исследование клиентской архитектуры mail/discuss в Odoo 19

Документ-карта: что и где лежит в ядре Odoo 19 (`/usr/lib/python3/dist-packages/odoo/addons/`,
окружение Oduflow `streams19`), какие точки расширения ядро реально предоставляет и как ими
пользуются сами модули Odoo (`im_livechat`, `hr`, `portal_rating`, `cloud_storage`, `crm_livechat`).

Все рецепты подтверждены цитатами из исходников 19.0. Пути даны от корня addons.

Референс старого UI (Odoo 15, messaging-фреймворк) — `addons/streams/static/legacy15/`.

---

## 0. Что изменилось принципиально по сравнению с 15

| Odoo 15 | Odoo 19 |
|---|---|
| `@mail/models` + `registerPatch` / `registerFieldPatchModel` | Классы `Record` в `@mail/model`, регистрация `Model.register()`, расширение — `patch(Model.prototype, {...})` из `@web/core/utils/patch` |
| Модели именуются `mail.thread_view_topbar`, `mail.message` (свои имена) | Модели именуются **по python-модели**: `mail.message`, `res.partner`, `discuss.channel.member`, `ir.attachment`. Исключения — «синтетические» модели: `Thread`, `Store`, `Composer`, `DiscussApp`, `DiscussAppCategory`, `ChatHub`, `ChatWindow` |
| `messaging_notification_handler` — один класс на все пуши шины | `bus_service.subscribe(type, cb)` в отдельных сервисах (`mail.core.common`, `discuss.core.common`, …) |
| Кнопки чаттера — QWeb-наследование `mail.ChatterTopbar` | Кнопки чаттера — тот же QWeb-xpath по `mail.Chatter`, но действия — методы `Chatter.prototype` |
| Шапка канала — модель `mail.thread_view_topbar` | Реестр **thread actions**: `registry.category("mail.thread/actions")` |
| Действия сообщения — жёстко в шаблоне | Реестр **message actions**: `registry.category("mail.message/actions")` |
| Кнопки композера — жёстко | Реестр **composer actions**: `registry.category("mail.composer/actions")` |
| QUnit | Hoot (`@odoo/hoot`) + tours (`web_tour.tours`) |

---

## 1. Клиентский Store и record-модели

### 1.1. Где что лежит

* Ядро ORM клиента: `mail/static/src/model/` — `record.js` (класс `Record`), `store.js`
  (класс `Store extends Record`, `store.insert()`), `store_internal.js` (`updateFields`,
  `updateAttr`, `updateRelation`), `misc.js` (объект `fields`, `modelRegistry`), `make_store.js`.
* Реэкспорт для бизнес-кода: `mail/static/src/core/common/record.js` — ровно одна строка:
  ```js
  export * from "@mail/model/export";
  ```
  То есть импортировать надо из `@mail/core/common/record` (`{ fields, Record, AND, OR }`).
* Store-сервис: `mail/static/src/core/common/store_service.js` — `class Store extends BaseStore`,
  сервис `mail.store`.
* Модели: `mail/static/src/core/common/thread_model.js` (`Thread`),
  `message_model.js` (`Message`, `static _name = "mail.message"`),
  `res_partner_model.js`, `attachment_model.js`, `mail_message_subtype_model.js` и т.д.

### 1.2. Реестр моделей и имена

`mail/static/src/model/misc.js`:
```js
export const modelRegistry = registry.category("discuss.model");
```
`mail/static/src/model/record.js`:
```js
static getName() {
    return this._name || this.name;
}
static register(localRegistry) {
    if (localRegistry) { localRegistry.add(this.getName(), this); }
    else { modelRegistry.add(this.getName(), this); }
}
```
Отсюда `Message` → `"mail.message"` (задано `static _name`), `Thread` → `"Thread"`
(имя класса, т.к. `_name` не задан).

Сопоставление python↔js для входящих данных — `store_service.js`:
```js
export const pyToJsModels = {
    "discuss.channel": "Thread",
    "mail.thread": "Thread",
};
export const addFieldsByPyModel = {
    "discuss.channel": { model: "discuss.channel" },
};
```
То есть серверный `Store` кладёт данные под ключами `"discuss.channel"`/`"mail.thread"`,
а клиент маршрутизирует их в модель `Thread` и **автоматически дописывает** `model: "discuss.channel"`.

### 1.3. Как серверный Store-протокол попадает в записи

Сервер отдаёт `{"<py.model>": [vals, ...], ...}`; клиент вызывает `store.insert(data)`
(`mail/static/src/model/store.js`):
```js
insert(dataByModelName = {}, options = {}) {
    ...
    for (const [pyOrJsModelName, data] of Object.entries(dataByModelName)) {
        const modelName = storeInsertFns.getActualModelName(store, ctx, pyOrJsModelName);
        if (!store[modelName]) {
            console.warn(`store.insert() received data for unknown model “${modelName}”.`);
            continue;
        }
        ...
        store[modelName].insert(insertData, options);
    }
}
```
Дальше `store_internal.js`:
```js
updateFields(record, vals) {
    const fieldEntries = Object.entries(vals).concat(...);
    for (const [fieldName, value] of fieldEntries) {
        if (!record.Model._.fields.get(fieldName) || record.Model._.fieldsAttr.get(fieldName)) {
            this.updateAttr(record, fieldName, value);
        } else {
            this.updateRelation(record, fieldName, value);
        }
    }
}
```

**Вывод для streams.** Наши серверные ключи попадут в клиентские записи *и без объявления*:
незнакомое поле уходит в `updateAttr` и просто присваивается на реактивный прокси. Но объявлять
надо — иначе нет: значения по умолчанию, типизации (`datetime`/`date`/`html`),
`compute`/`onUpdate`, реляционного разрешения и подсказок в `@types`.

Конкретно:

| Сервер (streams) | Модель клиента | Тип поля |
|---|---|---|
| `discuss.channel._to_store_defaults` → `channel_kind`, `res_model`, `res_id` | `Thread` | `fields.Attr()` |
| `discuss.channel._to_store_defaults` → `streams_filters` (dict `{comment: bool, ...}`) | `Thread` | `fields.Attr({...дефолты})` |
| `mail.message._to_store_defaults` → `streams_kind` (str) | `mail.message` | `fields.Attr(undefined)` |
| `mail.message._to_store_defaults` → `stream_channel_ids` (список int) | `mail.message` | `fields.Attr([])` — **не** `fields.Many("Thread")`, т.к. сервер отдаёт голые id, а `Many` ждёт объекты/`{id}` |

### 1.4. Рецепт: добавить свои поля в чужую модель

Канонический образец — `im_livechat/static/src/core/common/thread_model_patch.js`:
```js
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    setup() {
        super.setup();
        this.livechat_end_dt = fields.Datetime();
        this.livechat_operator_id = fields.One("res.partner");
        this.livechat_conversation_tag_ids = fields.Many("im_livechat.conversation.tag");
        this.livechatVisitorMember = fields.One("discuss.channel.member", {
            compute() { ... },
        });
    },
    get typesAllowingCalls() {
        return super.typesAllowingCalls.concat(["livechat"]);
    },
});
```

Наш вариант (`streams/static/src/core/common/thread_model_patch.js`):
```js
import { fields } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

export const STREAMS_FILTER_DEFAULTS = {
    activity: true, change: false, comment: true, message: true, note: true,
};

patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        /** @type {"record"|"changes"|"notifications"|false} */
        this.channel_kind = fields.Attr(false);
        this.res_model = fields.Attr(false);
        this.res_id = fields.Attr(false);
        this.streams_filters = fields.Attr({ ...STREAMS_FILTER_DEFAULTS });
    },
    get isStreamsRecordChannel() {
        return this.channel_kind === "record";
    },
    async streamsSetFilters(patchObj) {
        this.streams_filters = { ...this.streams_filters, ...patchObj };
        await this.store.env.services.orm.call(
            "discuss.channel", "streams_set_filters", [[this.id]], { filters: patchObj }
        );
    },
});
```

И `streams/static/src/core/common/message_model_patch.js`:
```js
import { fields } from "@mail/core/common/record";
import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        /** @type {"note"|"comment"|"message"|"change"|"activity"|undefined} */
        this.streams_kind = fields.Attr(undefined);
        /** @type {number[]} */
        this.stream_channel_ids = fields.Attr([]);
    },
    get isStreamsChange() {
        return this.streams_kind === "change";
    },
});
```

### 1.5. Своя новая модель (например «уведомление» `mail.notify`)

Образец — `im_livechat/static/src/core/common/livechat_channel_model.js` / `hr/.../hr_employee_model.js`:
```js
import { fields, Record } from "@mail/core/common/record";

export class StreamsNotify extends Record {
    static _name = "mail.notify";
    static id = "id";

    /** @type {number} */ id;
    subject = fields.Attr("");
    body = fields.Html("");
    create_date = fields.Datetime();
    author_id = fields.One("res.partner");
    res_model = fields.Attr(false);
    res_id = fields.Attr(false);
    attachment_ids = fields.Many("ir.attachment");
    sticky = false;
    timeout = 10;
}
StreamsNotify.register();
```
После этого записи доступны как `store["mail.notify"].insert({...})` / `.get(id)`,
а серверный `Store().add(notify)` попадёт в них автоматически.

### 1.6. Доступный API полей

`mail/static/src/model/misc.js`, объект `fields`:
`One(targetModel, {compute, eager, inverse, onAdd, onDelete, onUpdate})`,
`Many(targetModel, {..., sort})`, `Attr(default, {compute, eager, onUpdate, sort, type})`,
`Html(default, {...})`, `Date({...})`, `Datetime({...})`.
Идентификатор модели: `static id = "id"` либо `static id = AND("model", "id")` (как у `Thread`)
либо `OR(...)` (как у `Composer`: `static id = OR("thread", "message")`).

Патч **статики** модели тоже возможен — `patch(DiscussApp, {...})`
(см. `im_livechat/static/src/core/public_web/discuss_app_model_patch.js`, патч `new()`).

---

## 2. Chatter в Odoo 19

### 2.1. Файлы

* Базовый компонент: `mail/static/src/chatter/web_portal/chatter.js`
  — `class Chatter extends Component`, `static template = "mail.Chatter"`.
* Backend-надстройка: `mail/static/src/chatter/web/chatter_patch.js` — `patch(Chatter.prototype, {...})`,
  плюс `Object.assign(Chatter.components, {...})`, `Chatter.props.push(...)`, `Object.assign(Chatter.defaultProps, {...})`.
* Шаблон: `mail/static/src/chatter/web/chatter.xml` (`t-name="mail.Chatter"`).
* Встраивание в форму: `mail/static/src/chatter/web/form_compiler.js`, `form_renderer.js`,
  `form_controller.js`, `form_arch_parser.js`.

### 2.2. Топбар как он есть

`chatter.xml`, топбар (сокращённо):
```xml
<div class="o-mail-Chatter-topbar d-flex flex-shrink-0 flex-grow-0 overflow-x-auto">
    <div t-if="state.isSearchOpen" class="flex-grow-1"> <SearchMessageInput .../> </div>
    <t t-else="" name="chatter-topbar-left-buttons">
        <button class="o-mail-Chatter-sendMessage btn text-nowrap me-1" ... data-hotkey="m"
                t-on-click="() => this.toggleComposer('message')">Send message</button>
        <button class="o-mail-Chatter-logNote btn text-nowrap me-1" ... data-hotkey="shift+m"
                t-on-click="() => this.toggleComposer('note')">Log note</button>
        <button t-if="props.has_activities" class="o-mail-Chatter-activity btn btn-secondary text-nowrap"
                data-hotkey="shift+a" t-on-click="scheduleActivity"><span>Activity</span></button>
        <span class="o-mail-Chatter-topbarGrow flex-grow-1 pe-2"/>
        <button class="btn btn-link text-action" aria-label="Search Messages" t-on-click="onClickSearch">…</button>
    </t>
    …FileUploader / Followers…
</div>
```
Важные якоря для xpath: `name="chatter-topbar-left-buttons"`, классы
`o-mail-Chatter-sendMessage`, `o-mail-Chatter-logNote`, `o-mail-Chatter-activity`,
`o-mail-Chatter-topbar`, `o-mail-Chatter-topbarGrow`.

`toggleComposer` (chatter_patch.js:467):
```js
toggleComposer(mode = false, { force = false } = {}) {
    this.closeSearch();
    const toggle = async () => {
        if (!force && this.state.composerType === mode) { this.state.composerType = false; }
        else {
            if (mode === "message") { await this.updateRecipients(this.props.record, mode); }
            this.state.composerType = mode;
        }
    };
    if (this.state.thread.id) { toggle(); }
    else { this.onThreadCreated = toggle; this.props.saveRecord?.(); }
}
```
`state.composerType ∈ {false, "message", "note"}` и передаётся в `<Composer type="state.composerType"/>`.

Дополнительно `toggleComposer` пробрасывается в дочерний env (chatter_patch.js:254):
```js
get childSubEnv() {
    const res = Object.assign(super.childSubEnv, { messageHighlight: this.messageHighlight });
    assignGetter(res.inChatter, { aside: () => this.props.isChatterAside });
    Object.assign(res.inChatter, { toggleComposer: this.toggleComposer.bind(this) });
    return res;
}
```
— поэтому message action «Reply» умеет `owner.env.inChatter?.toggleComposer("note", { force: true })`.

### 2.3. Рецепт: свои кнопки топбара

Шаблон наследуется обычным QWeb-`t-inherit`. Единственный пример в ядре 19 —
`cloud_storage/static/src/chatter/web_portal/chatter_patch.xml`:
```xml
<templates xml:space="preserve">
    <t t-inherit="mail.Chatter" t-inherit-mode="extension">
        <xpath expr="//div[hasclass('o-mail-Chatter-topbar')]//FileUploader" position="attributes">
            <attribute name="checkSize">!cloudStorageUsable</attribute>
        </xpath>
    </t>
</templates>
```

Наш `streams/static/src/chatter/web/chatter_patch.xml` — переименовать ядровые и добавить свои:
```xml
<templates xml:space="preserve">
    <t t-inherit="mail.Chatter" t-inherit-mode="extension">
        <!-- Send message -> Comment (внутреннее общение сотрудников) -->
        <xpath expr="//button[hasclass('o-mail-Chatter-sendMessage')]" position="attributes">
            <attribute name="t-on-click">() => this.toggleComposer('comment')</attribute>
            <attribute name="title">Post an internal comment</attribute>
        </xpath>
        <xpath expr="//button[hasclass('o-mail-Chatter-sendMessage')]" position="inner">
            Comment
        </xpath>
        <!-- Log note -> Note -->
        <xpath expr="//button[hasclass('o-mail-Chatter-logNote')]" position="inner">Note</xpath>

        <!-- Send Message (внешняя переписка) + Notify + Changes -->
        <xpath expr="//button[hasclass('o-mail-Chatter-logNote')]" position="after">
            <button class="o-streams-Chatter-sendExternal btn btn-secondary text-nowrap me-1"
                    t-att-disabled="!state.thread.canPostMessage and props.threadId"
                    t-on-click="() => this.toggleComposer('message')">Send Message</button>
            <button class="o-streams-Chatter-notify btn btn-secondary text-nowrap me-1"
                    t-if="state.thread.id" t-on-click="() => this.onClickStreamsNotify()">Notify</button>
            <button class="o-streams-Chatter-changes btn btn-secondary text-nowrap me-1"
                    t-if="state.thread.id" t-on-click="() => this.onClickStreamsChanges()">Changes</button>
        </xpath>
    </t>
</templates>
```
и `streams/static/src/chatter/web/chatter_patch.js`:
```js
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(Chatter.prototype, {
    onClickStreamsNotify() {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Send a notification"),
            res_model: "mail.notify",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_res_model: this.props.threadModel,
                default_res_id: this.props.threadId,
            },
        });
    },
    onClickStreamsChanges() {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "streams.field.subscription.wizard",
            views: [[false, "form"]],
            target: "new",
            context: { default_res_model: this.props.threadModel,
                       default_res_id: this.props.threadId },
        });
    },
});
```

> Заметка про «Send Email». В 19 отдельной кнопки Send Email в чаттере нет — полный
> композер открывается из composer action (иконка «Open Full Composer»,
> `composer.js:onClickFullComposer`, экшен `mail.compose.message` с
> `default_subtype_xmlid`). Если нужна отдельная кнопка топбара — она делается по той же
> схеме, что и Notify, и вызывает `this.env.services.action.doAction` на `mail.compose.message`.

---

## 3. Composer: как отправляются сообщения

### 3.1. Цепочка

1. `Composer.sendMessage()` (`mail/static/src/core/common/composer.js:722`) → `processMessage(cb)` →
   `this._sendMessage(value, this.postData, this.extraData)`.
2. `Composer.postData` (composer.js:743):
   ```js
   get postData() {
       const composer = toRaw(this.props.composer);
       return {
           attachments: composer.attachments || [],
           emailAddSignature: composer.emailAddSignature,
           isNote: this.props.type === "note",
           mentionedChannels: ..., mentionedPartners: ..., mentionedRoles: ...,
           cannedResponseIds: composer.cannedResponses.map((c) => c.id),
           parentId: this.props.composer.replyToMessage?.id,
       };
   }
   ```
3. `Thread.post(body, postData, extraData)` (`thread_model.js:826`):
   ```js
   const params = await this.store.getMessagePostParams({ body, postData, thread: this });
   Object.assign(params, extraData);
   params.context = { ...user.context, ...params.context, temporary_id: tmpId };
   ...
   const data = await this.store.doMessagePost(params, tmpMsg);
   this.store.insert(data.store_data);
   const message = this.store["mail.message"].get(data.message_id);
   ```
4. `Store.getMessagePostParams` (`store_service.js:621`) — здесь выбирается подтип:
   ```js
   const subtype = isNote ? "mail.mt_note" : "mail.mt_comment";
   ...
   postData = {
       body: await generateEmojisOnHtml(body),
       email_add_signature: emailAddSignature,
       message_type: "comment",
       subtype_xmlid: subtype,
   };
   ...
   const params = { post_data: postData, thread_id: thread.id, thread_model: thread.model };
   ```
5. RPC: `POST /mail/message/post` (`mail/controllers/thread.py:201`), сигнатура
   `(thread_model, thread_id, post_data, context=None, **kwargs)`, ответ
   `{"store_data": ..., "message_id": ...}`.
   Для `discuss.channel` — тот же маршрут (`Thread.post` строит optimistic tmp-сообщение).

Полный композер (`composer.js:565 onClickFullComposer`) кладёт в контекст
`default_subtype_xmlid: this.props.type === "note" ? "mail.mt_note" : "mail.mt_comment"`.

### 3.2. Рецепт: третий тип композера (`message` = внешняя переписка)

В 19 `props.type` у `Composer` — свободная строка (`static props = [..., "type?"]`), проверяется
только сравнениями с `"note"`/`"message"`. Значит для streams достаточно ввести собственные
значения `"comment" | "note" | "message"` и перекрыть выбор подтипа.

`streams/static/src/core/common/store_service_patch.js` (образец —
`portal_rating/static/src/chatter/frontend/store_service_patch.js`):
```js
import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    async getMessagePostParams({ postData }) {
        const params = await super.getMessagePostParams(...arguments);
        if (postData.streamsKind) {
            params.post_data.subtype_xmlid = {
                note: "mail.mt_note",
                comment: "mail.mt_comment",
                message: "streams.mt_message",
            }[postData.streamsKind] ?? params.post_data.subtype_xmlid;
        }
        return params;
    },
});
```
`streams/static/src/core/common/composer_patch.js`:
```js
import { Composer } from "@mail/core/common/composer";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    get postData() {
        return Object.assign(super.postData, {
            isNote: this.props.type === "note",
            streamsKind: this.props.type || "comment",
        });
    },
    get placeholder() {
        if (this.props.type === "message") { return _t("Send an external message…"); }
        return super.placeholder;
    },
});
```
(образец патча `placeholder` — `mail/static/src/chatter/web_portal/composer_patch.js`.)

Важно: `getMessagePostParams` при `!isNote` подмешивает `thread.suggestedRecipients` +
`additionalRecipients` в `partner_ids`. Для потока `comment` (внутренний, без писем)
это, скорее всего, надо погасить — либо ставить `isNote: true` для `comment`
и подменять `subtype_xmlid` уже в патче, либо перекрывать `thread.suggestedRecipients`.
Это **решение, требующее подтверждения** при проектировании.

---

## 4. Discuss-приложение

### 4.1. Каркас

* Клиентский экшен: `mail/static/src/core/public_web/discuss_client_action.js` (+ `.xml`),
  `discuss.js` (`class Discuss`, `static template = "mail.Discuss"`), `discuss_content.js`.
* Сайдбар: `mail/static/src/core/public_web/discuss_sidebar.js`
  ```js
  export const discussSidebarItemsRegistry = registry.category("mail.discuss_sidebar_items");
  ```
  Рендер — `discuss_sidebar.xml`: `<t t-foreach="discussSidebarItems" t-as="item" t-component="item"/>`.
* Категории: `mail/static/src/discuss/core/public_web/discuss_sidebar_categories.js|.xml`;
  регистрация: `discussSidebarItemsRegistry.add("channels", DiscussSidebarCategories, { sequence: 30 });`
* Модель категории: `mail/static/src/discuss/core/public_web/discuss_app_category_model.js`
  (`DiscussAppCategory`, поля `id, name, icon, sequence, extraClass, hideWhenEmpty,
  serverStateKey, threads, threadsWithCounter, open, isVisible`).
* Модель приложения: `mail/static/src/core/public_web/discuss_app_model.js` (`DiscussApp`),
  расширение с категориями: `mail/static/src/discuss/core/public_web/discuss_app_model_patch.js`.

### 4.2. Рецепт: своя категория сайдбара

Образец — `im_livechat/static/src/core/public_web/discuss_app_model_patch.js` (две категории)
плюс `im_livechat/static/src/core/public_web/thread_model_patch.js` (маршрутизация тредов).

`streams/static/src/discuss/core/public_web/discuss_app_model_patch.js`:
```js
import { fields } from "@mail/core/common/record";
import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(DiscussApp.prototype, {
    setup() {
        super.setup(...arguments);
        this.streamsRecords = fields.One("DiscussAppCategory", {
            compute: () => ({
                extraClass: "o-streams-DiscussSidebarCategory-records",
                hideWhenEmpty: true,
                icon: "fa fa-folder-o",
                id: "streams.records",
                name: _t("Records"),
                sequence: 12,
            }),
            eager: true,
        });
        this.streamsChanges = fields.One("DiscussAppCategory", {
            compute: () => ({ icon: "fa fa-exchange", id: "streams.changes",
                              name: _t("Changes"), sequence: 13, hideWhenEmpty: true }),
            eager: true,
        });
        this.streamsNotifications = fields.One("DiscussAppCategory", {
            compute: () => ({ icon: "fa fa-bell-o", id: "streams.notifications",
                              name: _t("Notifications"), sequence: 14, hideWhenEmpty: true }),
            eager: true,
        });
    },
});
```
Маршрутизация треда в категорию — перекрыть `_computeDiscussAppCategory`
(им так и делает im_livechat, `thread_model_patch.js:_computeDiscussAppCategory`):
```js
patch(Thread.prototype, {
    _computeDiscussAppCategory() {
        switch (this.channel_kind) {
            case "record":        return this.store.discuss.streamsRecords;
            case "changes":       return this.store.discuss.streamsChanges;
            case "notifications": return this.store.discuss.streamsNotifications;
        }
        return super._computeDiscussAppCategory();
    },
});
```
Это же решает проблему из 15 (`legacy15/models/discuss_sidebar_category.js`): в 19 тред
принадлежит ровно одной категории — той, что вернул `_computeDiscussAppCategory`.

**Переименование ядровой категории** — тот же патч `DiscussApp.prototype`, перекрытие
`computeChats()` (уже вынесено в отдельный метод именно ради переопределения) либо
перекрытие compute-поля `channels`.

### 4.3. Бейджи непрочитанного

* Счётчик у категории: `DiscussAppCategory.threadsWithCounter` +
  `Thread.categoryAsThreadWithCounter` (compute в
  `mail/static/src/discuss/core/public_web/thread_model_patch.js`).
  Рендер в `discuss_sidebar_categories.xml`, шаблон `mail.DiscussSidebarCategory.main`:
  ```xml
  <div t-if="!category.open and category.threadsWithCounter.length > 0"
       class="o-mail-DiscussSidebar-badge shadow-sm badge rounded-pill o-discuss-badge fw-bold">
      <t t-esc="category.threadsWithCounter.length"/>
  </div>
  ```
* Индикаторы у канала: реестр в `discuss_sidebar_categories.js`
  ```js
  export const discussSidebarChannelIndicatorsRegistry =
      registry.category("mail.discuss_sidebar_channel_indicators");
  ```
  (компонент получает `thread`; используется `get indicators()` в `DiscussSidebarChannel`).
* Общий бейдж-шаблон: `mail.discuss_badge` в `mail/static/src/core/common/thread.xml`.

### 4.4. Шапка канала — thread actions

`mail/static/src/core/common/thread_actions.js`:
```js
export const threadActionsRegistry = registry.category("mail.thread/actions");
export function registerThreadAction(id, definition) {
    threadActionsRegistry.add(id, definition);
}
```
Ключи определения: `condition`, `icon`, `name`, `open`, `close`, `toggle`, `sequence`,
`sequenceGroup`, `sequenceQuick`, `hotkey`, `setup`, `badge`, `badgeText`, `badgeIcon`,
`tags`, `actionPanelComponent`, `actionPanelComponentProps`, `panelOuterClass`, `nameClass`.
Хук `useThreadActions({ thread })` собирает их в компоненте.

Примеры расширения из ядра: `hr/static/src/core/web/thread_actions.js` (`open-hr-profile`),
`crm_livechat/static/src/core/thread_actions.js` (`create-lead`),
`im_livechat/static/src/core/web/thread_actions.js` (`livechat-info` с боковой панелью),
`mail/static/src/discuss/core/public_web/thread_actions.js` (`member-list`, `show-threads`).

Наши фильтры потоков в шапке канала записи (замена `mail.thread_view_topbar` из 15):
```js
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { _t } from "@web/core/l10n/translation";
import { StreamsFilterPanel } from "./streams_filter_panel";

registerThreadAction("streams-filters", {
    actionPanelComponent: StreamsFilterPanel,
    actionPanelComponentProps: ({ thread }) => ({ thread }),
    condition: ({ thread }) => thread?.channel_kind === "record",
    icon: "fa fa-fw fa-filter",
    name: _t("Streams"),
    panelOuterClass: "o-streams-FilterPanel bg-inherit",
    sequence: 25,
    sequenceGroup: 20,
    toggle: true,
});
registerThreadAction("streams-invite-guest", {
    condition: ({ thread }) => thread?.channel_kind === "record",
    icon: "fa fa-fw fa-user-plus",
    name: _t("Invite customer"),
    open: ({ owner, thread }) => owner.env.services.action.doAction({
        type: "ir.actions.act_window", res_model: "streams.guest.invite.wizard",
        views: [[false, "form"]], target: "new",
        context: { default_channel_id: thread.id },
    }),
    sequence: 26, sequenceGroup: 20,
});
```

### 4.5. Лента сообщений и фильтрация

Компонент ленты: `mail/static/src/core/common/thread.js` (`class Thread`,
`static template = "mail.Thread"`), шаблон `thread.xml`.

Ключевое место — геттер `orderedMessages` (thread.js:668):
```js
get orderedMessages() {
    const messages = this.state.mountedAndLoaded
        ? this.props.thread.messages
        : this.props.thread.phantomMessages;
    return this.props.order === "asc" ? [...messages] : [...messages].reverse();
}
```
и в шаблоне `<t t-set="messages" t-value="orderedMessages"/>` + `t-foreach="messages"`.

**Рецепт клиентского фильтра потоков:**
```js
import { Thread } from "@mail/core/common/thread";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    get orderedMessages() {
        const messages = super.orderedMessages;
        const thread = this.props.thread;
        if (thread.channel_kind !== "record" && !this.env.inChatter) {
            return messages;
        }
        const filters = thread.streams_filters ?? {};
        return messages.filter((m) => filters[m.streams_kind ?? "comment"] !== false);
    },
});
```
Так же фильтр применим и к чаттеру (чаттер рендерит тот же `<Thread .../>`, см. `chatter.xml`).

> Осторожно: фильтрация только на клиенте ломает пагинацию/`Load More` (сервер отдаёт
> `FETCH_LIMIT = 30` сообщений *до* фильтра). В 15 фильтр был серверный — через
> `thread_cache` и домен. В 19 ту же роль играет серверный `_message_fetch` (у нас уже
> перекрыт в `models/mail_message.py`), поэтому правильнее: сервер фильтрует ленту,
> клиент только рисует тумблеры и перезагружает тред. См. «Риски».

### 4.6. Свой тип сообщения (change: «поле: было → стало»)

**Ядро уже это умеет.** `mail/static/src/core/web/message_patch.xml` наследует `mail.Message`
и рисует tracking values:
```xml
<t t-if="message.trackingValues.length">
    <ul class="mb-0 list-unstyled d-flex flex-column gap-1">
        <t name="trackingValues" t-foreach="message.trackingValues" t-as="trackingValue" t-key="trackingValue.id">
            <li class="o-mail-Message-tracking" role="group">
                <span class="o-mail-Message-trackingOld text-muted fw-bold"
                      t-out="formatTrackingOrNone(trackingValue.fieldInfo, trackingValue.oldValue)"/>
                <i class="o-mail-Message-trackingSeparator fa fa-long-arrow-right mx-2 text-600"/>
                <span class="o-mail-Message-trackingNew me-1 fw-bold text-info"
                      t-out="formatTrackingOrNone(trackingValue.fieldInfo, trackingValue.newValue)"/>
                <span class="o-mail-Message-trackingField ms-1 fst-italic text-muted">(<t
                      t-out="trackingValue.fieldInfo.changedField"/>)</span>
            </li>
        </t>
    </ul>
</t>
```
Поле `Message.trackingValues = []` объявлено в `message_model.js:172`.
Значит для потока `change` достаточно, чтобы сервер отдавал `trackingValues` — рендер бесплатный.
Дополнительная разметка (например, заголовок «запись-источник» в личном канале Changes) —
`t-inherit="mail.Message"` + xpath по `name="hasTrackingValue"`/`name="trackingValues"`.

Скрытие сообщений на уровне одного сообщения: в `thread.xml` условие
`<NotificationMessage t-if="msg.isNotification and !msg.notificationHidden" .../>` —
т.е. у `Message` есть штатный флаг `notificationHidden`, его тоже можно вычислять патчем.

Действия сообщения — `registry.category("mail.message/actions")`,
`registerMessageAction(id, def)` (`mail/static/src/core/common/message_actions.js:33`).

---

## 5. Systray

Реестр — `registry.category("systray")`, элемент: `{ Component }` + `{ sequence }`.

Примеры из ядра:
```js
// mail/static/src/core/web/activity_menu.js:124
registry.category("systray").add("mail.activity_menu", { Component: ActivityMenu }, { sequence: 20 });
// mail/static/src/core/public_web/messaging_menu.js:206
registry.category("systray").add("mail.messaging_menu", { Component: MessagingMenu }, { sequence: 25 });
// mail/static/src/discuss/call/common/call_menu.js:30
registry.category("systray").add("discuss.CallMenu", { Component: CallMenu }, { sequence: 100 });
```

Наш «колокол» — `streams/static/src/systray/streams_notify_menu.js`:
```js
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { useDropdownState } from "@web/core/dropdown/dropdown_hooks";
import { useDiscussSystray } from "@mail/utils/common/hooks";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class StreamsNotifyMenu extends Component {
    static components = { Dropdown };
    static props = [];
    static template = "streams.NotifyMenu";

    setup() {
        this.store = useService("mail.store");
        this.notify = useService("streams.notify");
        this.dropdown = useDropdownState();
        this.discussSystray = useDiscussSystray(this.dropdown);   // мобильный full-screen режим
    }
    get counter() { return this.notify.state.counter; }
    onBeforeOpen() { this.notify.fetchFeed(); }
}

registry.category("systray").add(
    "streams.notify_menu", { Component: StreamsNotifyMenu }, { sequence: 22 }
);
```
`useDiscussSystray` — `mail/static/src/utils/common/hooks.js:~550`, даёт классы
`o-mail-systrayFullscreenDropdownMenu` и метку на `document.body`, как у ядровых меню.

---

## 6. Оверлеи и попапы поверх интерфейса

### 6.1. `main_components`

`registry.category("main_components")` — компоненты, монтируемые в
`MainComponentsContainer` (`web/static/src/core/main_components_container.js`) поверх всего.

Ядро mail использует его для chat hub:
```js
// mail/static/src/core/common/chat_hub.js:186
registry.category("main_components").add("mail.ChatHub", { Component: ChatHub });
```
и для алерта шины:
```js
// mail/static/src/discuss/core/public_web/bus_connection_alert.js:23
registry.category("main_components").add(...)
```

Web-ядро так же вешает контейнер уведомлений (`notification_service.js`):
```js
registry.category("main_components").add(
    this.notificationContainer.name,
    { Component: this.notificationContainer, props: { notifications } },
    { sequence: 100 }
);
```

### 6.2. Штатный notification service

`web/static/src/core/notifications/notification_service.js`, API:
```js
add(message, {
    title, autocloseDelay = 4000, type: "warning"|"danger"|"success"|"info",
    sticky = false, className, onClose, buttons: [{ name, icon, primary, onClick }]
})  // → возвращает closeFn
```
Ограничения те же, что были в 15: **`message` — только строка**, компонент вставить нельзя,
`autocloseDelay` настраивается, но пагинатора/стека с переключением нет.

### 6.3. Рецепт для streams-Notify

Как и в 15 — свой сервис + свой контейнер в `main_components`. Это и есть штатный путь:
```js
// streams/static/src/notify/streams_notify_service.js
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { StreamsNotifyContainer } from "./streams_notify_container";

export const streamsNotifyService = {
    dependencies: ["action", "bus_service", "mail.store", "orm", "dialog"],
    start(env, { bus_service: bus, orm, action }) {
        const state = reactive({ counter: 0, popups: [], stickyIndex: 0 });

        registry.category("main_components").add(
            "streams.NotifyContainer",
            { Component: StreamsNotifyContainer, props: { state } },
            { sequence: 110 }          // выше ядровых нотификаций (100)
        );

        bus.subscribe("streams.notify/new", (payload) => { /* push + timeout */ });
        bus.subscribe("streams.notify/update", (payload) => { /* patch */ });
        bus.subscribe("streams.notify/counter", ({ counter }) => { state.counter = counter; });

        return state;
    },
};
registry.category("services").add("streams.notify", streamsNotifyService);
```
Альтернатива для одиночных всплывашек с позиционированием — `overlay`-сервис
(`web/static/src/core/overlay/overlay_service.js`) и `usePopover`
(`@web/core/popover/popover_hook`; так делает thread action `show-threads`).
Для нашего стека sticky+timeout+пагинатор `main_components` проще и точнее.

---

## 7. Шина в клиенте 19

### 7.1. API

`bus/static/src/services/bus_service.js`, сервис `bus_service`:
```js
subscribe(notificationType, callback)   // callback(payload, { id })
unsubscribe(notificationType, callback)
addChannel(channel) / deleteChannel(channel)
start() / stop() / isActive
addEventListener / removeEventListener / trigger      // «сырые» worker-события BUS:*
```
`subscribe` даёт **глубокую копию** payload (`JSON.parse(JSON.stringify(payload))`).

Хук для компонентных подписок на обычный `EventBus` — `useBus(bus, eventName, cb)`
(`web/static/src/core/utils/hooks.js:87`); он для `env.bus`, не для `bus_service`.

### 7.2. Как ядро обрабатывает свои типы

`mail/static/src/core/common/mail_core_common_service.js` — сервис `mail.core.common`:
```js
setup() {
    this.busService.subscribe("ir.attachment/delete", (payload) => {...});
    this.busService.subscribe("mail.message/delete", (payload, { id: notifId }) => {...});
    this.busService.subscribe("mail.message/toggle_star", ...);
    this.busService.subscribe("res.users.settings", (payload) => { this.store.settings.update(payload); });
    this.busService.subscribe("mail.record/insert", (payload) => { this.store.insert(payload); });
}
```
`mail/static/src/discuss/core/common/discuss_core_common_service.js` — сервис `discuss.core.common`:
```js
this.busService.subscribe("discuss.channel/delete", (payload, metadata) => {...});
this.busService.subscribe("discuss.channel/new_message", (payload, metadata) => {
    // Insert should always be done before any async operation.
    this.store.insert(payload.data);
    this._handleNotificationNewMessage(payload, metadata);
});
this.busService.subscribe("discuss.channel/transient_message", ...);
this.busService.subscribe("discuss.channel.member/fetched", ...);
```
`_handleNotificationNewMessage` затем триггерит внутреннее событие
`this.env.bus.trigger("discuss.channel/new_message", { channel, message, silent })`.

Ключевое: **`mail.record/insert` — универсальный канал доставки любых store-данных.**
Наш сервер уже так шлёт (`mail_notify.py:484` — `Store().add(channel).get_result()`).

### 7.3. Рецепт: свои типы шины

Отдельный сервис по образцу `mail.core.common`
(`streams/static/src/core/common/streams_core_service.js`):
```js
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class StreamsCore {
    constructor(env, services) {
        this.env = env;
        this.busService = services.bus_service;
        this.store = services["mail.store"];
        this.notify = services["streams.notify"];
    }
    setup() {
        this.busService.subscribe("streams.notify/new", (payload) => {
            if (payload.store_data) { this.store.insert(payload.store_data); }
            this.notify.pushPopup(payload);
        });
        this.busService.subscribe("streams.notify/update", (payload) => {
            this.store["mail.notify"].insert(payload);
            this.notify.patchPopup(payload);
        });
        this.busService.subscribe("streams.notify/counter", ({ counter }) => {
            this.notify.state.counter = counter;
        });
        this.busService.subscribe("streams.changes/updated", (payload) => {
            this.store.insert(payload);          // ре-используем store-протокол
        });
    }
}

export const streamsCore = {
    dependencies: ["bus_service", "mail.store", "streams.notify"],
    start(env, services) {
        const svc = reactive(new StreamsCore(env, services));
        svc.setup();
        return svc;
    },
};
registry.category("services").add("streams.core", streamsCore);
```
Подписка на дополнительный bus-канал (если сервер шлёт не в `partner._bus_send`, а в именованный
канал) — `busService.addChannel("streams.notify")`, как делает im_livechat
(`busService.addChannel("im_livechat.looking_for_help")` в `discuss_app_model_patch.js`).

---

## 8. Голосовая запись

**В ядре 19 она есть и переиспользуема.**
`mail/static/src/discuss/voice_message/common/`:

| Файл | Что даёт |
|---|---|
| `voice_recorder.js` | Хук `useVoiceRecorder()` — MediaRecorder-подобная запись через `AudioWorklet` + mp3-энкодер, таймер, лимит 60 с, `state.onClick()` |
| `mp3_encoder.js` | Обёртка над lamejs |
| `voice_message_service.js` | `loadLamejs()` (ленивая загрузка бандла `mail.assets_lamejs`) |
| `voice_player.js|.xml` | Компонент воспроизведения с волной |
| `voice_metadata_model.js` | Модель `DiscussVoiceMetadata` |
| `composer_actions_patch.js` | Регистрация кнопок composer-action `voice-start`/`voice-stop`/`voice-recording` |
| `attachment_uploader_hook_patch.js`, `attachment_model_patch.js` | Пометка вложения как voice |

Ключевые ограничения:
* `useVoiceRecorder()` требует, чтобы в компоненте был `this.attachmentUploader`
  (`component.attachmentUploader.uploadFile(file, { voice: true })`);
* ядровые composer-actions включены только для `composer.targetThread?.model === "discuss.channel"`:
  ```js
  condition: ({ composer, owner }) =>
      composer.targetThread?.model === "discuss.channel" && owner.voiceRecorder && ...
  ```
  Чтобы включить запись в форме Notify — регистрируем **свой** composer action
  с нужным `condition`, но переиспользуем `useVoiceRecorder`;
* воркер: `/discuss/voice/worklet_processor` (контроллер mail), лимит 1 минута зашит в хук.

Загрузка вложений — `mail/static/src/core/common/attachment_upload_service.js`:
```js
getUploadURL(thread) { return "/mail/attachment/upload"; }
_buildFormData(formData, tmpURL, thread, composer, tmpId, options) {
    formData.append("thread_id", thread.id);
    formData.append("tmp_url", tmpURL);
    formData.append("thread_model", thread.model);
    formData.append("is_pending", Boolean(composer));
    formData.append("temporary_id", tmpId);
    if (options?.activity) { formData.append("activity_id", options.activity.id); }
}
```
Контроллер — `mail/controllers/attachment.py:49`, `POST /mail/attachment/upload` (`type="http"`),
ответ `{ data: { store_data, attachment_id } }`. Хук в компоненте —
`useAttachmentUploader(thread, { composer })` (`attachment_uploader_hook.js`).

Итого: **свой рекордер писать не нужно**, достаточно `useVoiceRecorder()` + свой
`registerComposerAction` + `useAttachmentUploader` на нашем «псевдо-треде» формы Notify.

---

## 9. Ассеты и структура каталогов

### 9.1. Манифест

`mail/__manifest__.py`, ключевые бандлы:
```python
'assets': {
    'web._assets_primary_variables': ['mail/static/src/**/primary_variables.scss'],
    'web.assets_backend': [
        'mail/static/src/scss/variables/derived_variables.scss',
        'mail/static/src/scss/*.scss',
        'mail/static/src/js/**/*',
        'mail/static/src/model/**/*',
        'mail/static/src/core/common/**/*',
        'mail/static/src/core/public_web/**/*',
        'mail/static/src/core/web_portal/**/*',
        'mail/static/src/core/web/**/*',
        'mail/static/src/**/common/**/*',
        'mail/static/src/**/public_web/**/*',
        'mail/static/src/**/web_portal/**/*',
        'mail/static/src/**/web/**/*',
        ('remove', 'mail/static/src/**/*.dark.scss'),
        ('remove', 'mail/static/src/discuss/**/*'),        # discuss грузится последним
        'mail/static/src/discuss/core/common/**/*',
        ...
    ],
    'web.assets_web_dark': ['mail/static/src/**/*.dark.scss'],
    'web.assets_unit_tests': ['mail/static/tests/**/*', ('remove', 'mail/static/tests/tours/**/*')],
    'web.assets_tests': ['mail/static/tests/tours/**/*'],
    'mail.assets_lamejs': ['mail/static/lib/lame/lame.js'],
}
```

### 9.2. Соглашения каталогов (mail и модули-расширения)

```
static/src/
    core/common/        # общее ядро (backend + public discuss)
    core/public_web/    # discuss-приложение + messaging menu
    core/web_portal/
    core/web/           # только backend
    chatter/web_portal/ # базовый чаттер
    chatter/web/        # backend-чаттер (activities, followers, scheduled msgs)
    discuss/core/common|public_web|web|public/
    discuss/<feature>/common|web/     # call, voice_message, message_pin, gif_picker
    utils/common/
    model/
```
Имена файлов: `<thing>_model.js` (Record-модель), `<thing>_model_patch.js` (патч чужой модели),
`<thing>_patch.js` (патч компонента), `<thing>_patch.xml` (наследование шаблона),
`<thing>_service.js`, `<thing>_actions.js` (реестры действий), `<thing>.scss`, `<thing>.dark.scss`.

Так же устроены модули-расширители: `im_livechat/static/src/core/{common,web,public_web}/`,
`im_livechat/static/src/embed/{common,cors}/`, `hr/static/src/core/{common,web}/`.

### 9.3. Предлагаемая раскладка для streams

```
streams/static/src/
    core/common/thread_model_patch.js        # channel_kind, res_model/res_id, streams_filters
    core/common/message_model_patch.js       # streams_kind, stream_channel_ids
    core/common/store_service_patch.js       # getMessagePostParams -> subtype
    core/common/composer_patch.js            # postData.streamsKind, placeholder
    core/common/streams_core_service.js      # bus.subscribe("streams.*")
    core/common/thread_patch.js              # orderedMessages -> фильтр (если клиентский)
    core/common/message_patch.xml            # доп. разметка change-сообщений
    chatter/web/chatter_patch.js|.xml        # кнопки Comment/Note/Send Message/Notify/Changes
    discuss/core/public_web/discuss_app_model_patch.js   # категории сайдбара
    discuss/core/public_web/thread_model_patch.js        # _computeDiscussAppCategory
    discuss/core/common/thread_actions.js                # фильтры/invite в шапке канала
    notify/streams_notify_service.js                     # сервис + main_components
    notify/streams_notify_container.js|.xml|.scss        # стек попапов
    notify/streams_notify_composer.js|.xml               # форма Notify (+ voice)
    systray/streams_notify_menu.js|.xml                  # колокол
    scss/streams.scss
```
Манифест:
```python
'assets': {
    'web.assets_backend': [
        'streams/static/src/scss/*.scss',
        'streams/static/src/core/common/**/*',
        'streams/static/src/chatter/**/*',
        'streams/static/src/notify/**/*',
        'streams/static/src/systray/**/*',
        'streams/static/src/discuss/**/*',
        ('remove', 'streams/static/src/**/*.dark.scss'),
    ],
    'web.assets_web_dark': ['streams/static/src/**/*.dark.scss'],
    'web.assets_unit_tests': ['streams/static/tests/**/*',
                              ('remove', 'streams/static/tests/tours/**/*')],
    'web.assets_tests': ['streams/static/tests/tours/**/*'],
}
```
Порядок важен: наши патчи должны грузиться **после** ядровых — так и будет, поскольку
бандл собирается по порядку зависимостей модулей (`streams` depends on `mail`).
Существующий `static/legacy15/**` в assets не попадает (в манифесте его нет) — оставить как есть.

---

## 10. Тестируемость

### 10.1. Unit-тесты — Hoot

* Бандл: `web.assets_unit_tests`; файлы `<module>/static/tests/**/*.test.js`.
* Импорты: `@odoo/hoot` (`describe`, `test`, `expect`), `@odoo/hoot-mock` (`advanceTime`, `Deferred`),
  `@odoo/hoot-dom` (`queryFirst`, `click`, …), `@web/../tests/web_test_helpers`
  (`onRpc`, `mockService`, `serverState`, `defineModels`, `asyncStep`, `waitForSteps`),
  `@mail/../tests/mail_test_helpers` (`start`, `startServer`, `openFormView`, `openDiscuss`,
  `click`, `contains`, `insertText`, `defineMailModels`, `patchUiSize`, `triggerHotkey`).
* Mock-сервер: `mail/static/tests/mock_server/mail_mock_server.js`
  (`registerRoute("/mail/message/post", mail_message_post)` и т.д.) плюс mock-модели в
  `mail/static/tests/mock_server/mock_models/`.

Минимальный пример (по образцу `mail/static/tests/chatter/web/chatter.test.js`):
```js
// streams/static/tests/chatter_buttons.test.js
import { click, contains, defineMailModels, openFormView, start, startServer }
    from "@mail/../tests/mail_test_helpers";
import { describe, test } from "@odoo/hoot";
import { defineModels } from "@web/../tests/web_test_helpers";
import { defineStreamsModels } from "./streams_test_helpers";   // наши mock-модели

describe.current.tags("desktop");
defineMailModels();
defineStreamsModels();

test("chatter shows Comment / Note / Send Message / Notify / Changes", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John Doe" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Chatter-sendMessage", { text: "Comment" });
    await contains(".o-mail-Chatter-logNote", { text: "Note" });
    await contains(".o-streams-Chatter-sendExternal", { text: "Send Message" });
    await contains(".o-streams-Chatter-notify");
    await click(".o-streams-Chatter-changes");
    await contains(".modal");
});
```

Запуск (как это делает web в `web/tests/test_js.py:191`):
```
/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&filter=streams
```
через `HttpCase.browser_js(..., success_signal="[HOOT] Test suite succeeded")`.
Интерактивно — просто открыть `/web/tests` в браузере окружения и отфильтровать по модулю.
Через Oduflow: `run_odoo_tests(env_name="streams19", modules="streams")` подхватит python-класс,
который дергает `browser_js`; сам по себе `--test-enable` Hoot-тесты не запускает — нужен
python-тест-обёртка (см. `web/tests/test_js.py`, класс `HOOTCommon`).

### 10.2. Tour-тесты

* Бандл `web.assets_tests`, файлы `<module>/static/tests/tours/*.js`.
* Регистрация: `registry.category("web_tour.tours").add("<name>", { steps: () => [...] })`.
* Шаг: `{ trigger: "<css>", run: "click" | "edit текст" | async function }`.
* Образец: `mail/static/tests/tours/discuss_channel_public_tour.js`.
* Запуск из python: `HttpCase.start_tour("/odoo", "<tour_name>", login="admin")`.

Пример:
```js
// streams/static/tests/tours/streams_chatter_tour.js
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("streams_chatter_tour", {
    steps: () => [
        { trigger: ".o-mail-Chatter-topbar" },
        { trigger: ".o-streams-Chatter-sendExternal", run: "click" },
        { trigger: ".o-mail-Composer-input", run: "edit hello customer" },
        { trigger: ".o-mail-Composer button[title='Send']:enabled", run: "click" },
        { trigger: ".o-mail-Message:contains('hello customer')" },
    ],
});
```

---

## Сводка: главные точки расширения

| № | Что | Механизм | Файл-образец в ядре 19 |
|---|---|---|---|
| 1 | Поля клиентских моделей | `patch(Thread.prototype, { setup() { this.x = fields.Attr(...) } })` | `im_livechat/.../core/common/thread_model_patch.js` |
| 2 | Своя модель | `class X extends Record { static _name = "py.model" } X.register()` | `im_livechat/.../livechat_channel_model.js` |
| 3 | Приём store-данных с сервера | `_to_store_defaults` (py) → `store.insert()` — работает без клиентского кода, объявление поля добавляет типизацию/compute | `mail/static/src/model/store.js` |
| 4 | Кнопки чаттера | `t-inherit="mail.Chatter"` + `patch(Chatter.prototype, {...})`, состояние `state.composerType` | `cloud_storage/.../chatter_patch.xml` |
| 5 | Подтип отправки | `patch(Store.prototype, { getMessagePostParams })` | `portal_rating/.../store_service_patch.js` |
| 6 | Поведение композера | `patch(Composer.prototype, { postData, placeholder })`, `props.type` | `mail/static/src/chatter/web_portal/composer_patch.js` |
| 7 | Кнопки шапки канала | `registerThreadAction(id, def)` → `registry.category("mail.thread/actions")` | `im_livechat/.../core/web/thread_actions.js`, `hr/.../thread_actions.js` |
| 8 | Действия сообщения | `registerMessageAction` → `"mail.message/actions"` | `mail/static/src/core/common/message_actions.js` |
| 9 | Кнопки композера (в т.ч. voice) | `registerComposerAction` → `"mail.composer/actions"` | `mail/static/src/discuss/voice_message/common/composer_actions_patch.js` |
| 10 | Категории сайдбара Discuss | `patch(DiscussApp.prototype)` + `fields.One("DiscussAppCategory", {compute})`, маршрутизация `_computeDiscussAppCategory` | `im_livechat/.../core/public_web/{discuss_app,thread}_model_patch.js` |
| 11 | Блоки сайдбара / индикаторы | `discussSidebarItemsRegistry` (`"mail.discuss_sidebar_items"`), `discussSidebarChannelIndicatorsRegistry` | `mail/.../discuss_sidebar_categories.js` |
| 12 | Фильтр ленты | `patch(Thread.prototype /* компонент */, { get orderedMessages })` | `mail/static/src/core/common/thread.js:668` |
| 13 | Рендер change-сообщений | уже готово: `message.trackingValues` + `mail/static/src/core/web/message_patch.xml` | — |
| 14 | Systray | `registry.category("systray").add(id, { Component }, { sequence })` | `mail/.../activity_menu.js:124` |
| 15 | Оверлеи/попапы | `registry.category("main_components")` + свой reactive-state; либо `notification` / `overlay` / `usePopover` | `mail/.../chat_hub.js:186`, `web/.../notification_service.js` |
| 16 | Шина | `bus_service.subscribe(type, cb)` в своём сервисе; `addChannel` для именованных каналов | `mail/.../mail_core_common_service.js`, `discuss_core_common_service.js` |
| 17 | Голос | `useVoiceRecorder()` из `@mail/discuss/voice_message/common/voice_recorder` + `useAttachmentUploader` | `mail/.../voice_recorder.js` |
| 18 | Вложения | `POST /mail/attachment/upload` (http), form-data `thread_id/thread_model/is_pending/temporary_id` | `attachment_upload_service.js:_buildFormData` |

---

## Риски

1. **Клиентская фильтрация ломает пагинацию.** `Thread.FETCH_LIMIT = 30` — сервер отдаёт 30
   сообщений *до* нашего фильтра. Если поток `change` выключен, а последние 30 сообщений —
   change'и, лента будет визуально пустой при непустом треде, и «Load More» надо будет жать
   вслепую. Правильный путь: фильтровать на сервере (наш `_message_fetch` уже перекрыт),
   а клиент при переключении тумблера делает `thread.messages.length = 0; thread.fetchNewMessages()`.
   Требуется решение при проектировании.

2. **`Thread` — не python-модель.** В 19 треды чаттера и каналы — одна js-модель `Thread`
   с `static id = AND("model", "id")`; серверные ключи приходят под `"discuss.channel"` и
   `"mail.thread"`. Наши `channel_kind`/`res_model`/`res_id` есть только у `discuss.channel`,
   значит любой код должен быть готов к `undefined` на чаттерных тредах.
   Особая ловушка: `Thread.res_model` конфликтует по смыслу с ядровым `Thread.model`
   (для канала записи `model === "discuss.channel"`, а `res_model` — модель записи-источника).

3. **Тип композера.** `props.type` в ядре сравнивается с литералами `"note"`/`"message"`
   в ≥6 местах (`composer.js`, `chatter.xml`, `chatter_patch.js`, `store_service.js`).
   Введение третьего значения `"comment"` требует аудита всех этих сравнений: например
   `if (this.props.type !== "note")` в `sendMessage()` валидирует email-получателей —
   для внутреннего `comment` это лишнее и заблокирует отправку.

4. **`getMessagePostParams` подмешивает получателей.** При `!isNote` в `partner_ids` попадают
   `thread.suggestedRecipients` + `additionalRecipients`. Для streams это прямое нарушение
   «никакой автоматической внешней рассылки» — нужен явный патч.

5. **Автоподписка.** В 19 ядро уже само отказалось от autofollow
   (`// Changed in 18.2+: finally get rid of autofollow` в `store_service.js` и `composer.js`),
   но контроллер `/mail/message/post` всё ещё ставит
   `mail_post_autofollow_author_skip=True, mail_post_autofollow=False` только при отсутствии
   write-доступа. Серверная часть уже портирована — проверить, что клиентские патчи ничего
   не возвращают обратно.

6. **Хрупкость xpath по шаблонам.** У `mail.Chatter` мало именованных якорей
   (`chatter-topbar-left-buttons`, `empty-message`, `content`, `hasTrackingValue`,
   `trackingValues`, `header`, `titleText`, `action-group`, `root`). Остальное — `hasclass()`.
   Классы `o-mail-Chatter-sendMessage`/`o-mail-Chatter-logNote` стабильны (на них опираются
   тесты ядра), но при минорных обновлениях 19.x проверять.

7. **Voice-рекордер привязан к `discuss.channel`.** Ядровые composer actions
   (`voice-start`/`voice-stop`) включаются только для каналов; форма Notify каналом не является.
   Нужен свой `registerComposerAction` + собственный носитель `attachmentUploader`.

8. **Notify-попапы: конкуренция за `main_components`.** Ядровые нотификации сидят на
   `sequence: 100`, chat hub — без sequence. Нужен явный sequence и продуманный z-index,
   иначе стек Notify будет перекрываться chat hub / file viewer.

9. **`bus_service.subscribe` отдаёт глубокую копию.** `JSON.parse(JSON.stringify(payload))` —
   `Date`/`markup` не переживут. Тела уведомлений надо доставлять как строки и оборачивать
   `markup()` уже на клиенте, либо (лучше) слать через `mail.record/insert` + `fields.Html`.

10. **Hoot требует mock-моделей.** Наши `mail.notify`, `streams.field.subscription` и патчи
    `discuss.channel`/`mail.message` придётся объявить в `static/tests/mock_server/mock_models/`
    и зарегистрировать своим `defineStreamsModels()`, иначе тесты чаттера падают на
    неизвестных полях/маршрутах. Это заметный объём работы — заложить в оценку фазы.

11. **`static/legacy15` остаётся в репозитории**, но не в assets. Убедиться, что новые
    glob'ы манифеста (`streams/static/src/**`) его не захватывают, иначе бандл упадёт на
    `/** @odoo-module **/` + импортах несуществующего `@mail/model/model_core`.
