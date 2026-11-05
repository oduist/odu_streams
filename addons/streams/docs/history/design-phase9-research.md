# Фаза 9 — исследование ядра 19 под виртуальный чаттер партнёра

Документ отвечает на 8 вопросов постановки фазы 9. ТЗ — `docs/roadmap.md` §18.
Технический дизайн, написанный под Odoo 15, — `docs/design-virtual-chatter.md`;
раздел «Решения по развилкам (2026-08-18)» в его конце остаётся в силе, всё,
что там про клиент 15 (`thread_cache.js`, `_computeThreads`,
`registerFieldPatchModel`, `ChatterTopbar`), — мертво.

**Метод.** Каждый факт — из реального кода окружения `streams19`
(Odoo 19.0-20260817, `/usr/lib/python3/dist-packages/odoo/addons/...`),
с `file:line`. Ключевые утверждения дополнительно проверены прогоном в
`odoo shell` (помечены «ПРОВЕРЕНО»). Пути ядра ниже даются относительно
`/usr/lib/python3/dist-packages/odoo/`.

---

## 1. Путь ленты чаттера в 19 на сервере и куда врезать агрегат

### 1.1. Факты

| Факт | file:line |
|---|---|
| Роут ленты чаттера: `POST /mail/thread/messages`, `type="jsonrpc"`, `auth="user"`, сигнатура `mail_thread_messages(self, thread_model, thread_id, fetch_params=None)` | `addons/mail/controllers/thread.py:61-72` |
| Роут **сам проверяет права на запись-тред**: `thread = self._get_thread_with_access(thread_model, thread_id, mode="read")` | `addons/mail/controllers/thread.py:63` |
| Роут вызывает `request.env["mail.message"]._message_fetch(domain=None, thread=thread, **(fetch_params or {}))` — то есть **чаттерный путь идёт через тот же `_message_fetch`**, что и каналы, с `thread` = recordset самой записи | `addons/mail/controllers/thread.py:64` |
| После выборки — `messages.set_message_done()` (гашение needaction) и `Store().add(messages)` | `addons/mail/controllers/thread.py:65-72` |
| `_message_fetch(self, domain, *, thread=None, search_term=None, is_notification=None, before=None, after=None, around=None, limit=30)` | `addons/mail/models/mail_message.py:947` |
| Сужение по треду внутри `_message_fetch`: `domain &= res_id = thread.id AND model = thread._name AND message_type != 'user_notification'` | `addons/mail/models/mail_message.py:950-955` |
| Пагинация: `before` → `id <` , `after` → `id >`, `around` → две половинные выборки | `mail_message.py:983-990` |
| Финальная выборка страницы: `res["messages"] = self.search(domain, limit=limit, order='id ASC' if after else 'id DESC')` | `mail_message.py:991` |
| `_get_thread_with_access(thread_id, mode="read")` → `browse().exists()` + `sudo(False).with_context(allowed_company_ids=[]).has_access(mode)`; при отказе — пустой recordset | `addons/mail/models/mail_thread.py:5126-5140` |
| Клиент выбирает роут: `getFetchRoute()` → `discuss.channel` → `/discuss/channel/messages`, `mail.box` → инбоксы, иначе `this.fetchRouteChatter` = `/mail/thread/messages` | `addons/mail/static/src/core/common/thread_model.js:642-659` |
| Параметры запроса: `getFetchParams()` для не-канала = `{thread_id, thread_model, ...this.rpcParams}`; `rpcParams` — пустой геттер, штатная точка расширения | `thread_model.js:628-640`, `458-460` |

**ПРОВЕРЕНО** (odoo shell): `env['mail.message']._message_fetch(domain=None, thread=partner, limit=5)`
возвращает `{'messages': ...}` и разрешается в **наш** форк
(`<function MailMessage._message_fetch>` из `addons/streams`), то есть врезка
модуля уже стоит на чаттерном пути res.partner.

### 1.2. Вывод: как делаем в 19

**Расширяем наш форк `mail.message._message_fetch`, роут НЕ трогаем.**
Это разворот решения B.3 дизайна 15, и он обоснован изменениями самого 19:

1. **Довод «в 15 роут не проверял прав на тред» исчез.** В 15 мы выбирали
   override роута в том числе потому, что ядровый `/mail/thread/messages`
   не проверял доступ к треду вообще, и нам всё равно надо было писать
   свою проверку. В 19 проверка встроена в роут
   (`thread.py:63` → `mail_thread.py:5126-5140`) и делается ДО вызова
   `_message_fetch`. Дублировать её незачем, а override роута заставил бы
   её воспроизводить.

2. **`_message_fetch` в 19 получает `thread` как recordset, а не как домен.**
   В 15 приходилось распознавать «это чаттер такой-то записи» по форме
   домена (хрупкий детектор `velesagro_crm`). В 19 признак явный:
   `thread._name == 'res.partner' and len(thread) == 1`. Никакого разбора
   доменов.

3. **У нас уже есть форк ровно этой сигнатуры** —
   `models/mail_message.py:360-388`, где мы для `discuss.channel` с
   `channel_kind` разворачиваем тред в домен проекций и обнуляем `thread`,
   после чего работает ядровая пагинация. Партнёрская ветка ложится в тот
   же шаблон один-в-один.

4. **Один вход обслуживает все потребителей.** Через `_message_fetch`
   идут и `/mail/thread/messages`, и (при желании) поиск по ленте
   (`search_term`), и `around`-переходы, и наше мобильное API. Override
   роута покрыл бы только один из них.

Каркас врезки (симметрично существующей канальной ветке):

```python
def _message_fetch(self, domain, *, thread=None, ..., limit=30):
    if thread is not None and thread._name == 'res.partner' and len(thread) == 1:
        scope = self.env.user._streams_partner_scope()          # direct/related/company
        if scope != 'direct':
            domain = Domain(domain or Domain.TRUE) & self._streams_partner_domain(thread, scope)
            thread = None                                        # дальше — ядровая пагинация
    if thread is not None and thread._name == 'discuss.channel' ...:
        ...  # существующая ветка
    return super()._message_fetch(domain, thread=thread, ..., limit=limit)
```

Важно: обнуляя `thread`, мы теряем ядровое `message_type != 'user_notification'`
(`mail_message.py:954`) — как и в канальной ветке, его надо добавить в
`_streams_partner_domain` явно (в канальной ветке это уже сделано,
`models/mail_message.py:377-378`).

---

## 2. ACL в 19: over-fetch, утечки, ловушки

### 2.1. Факты

| Факт | file:line |
|---|---|
| `mail.message._search(self, domain, offset=0, limit=None, order=None, *, bypass_access=False, **kwargs)` | `addons/mail/models/mail_message.py:317` |
| Суперюзер / `bypass_access` → ранний выход без фильтрации | `mail_message.py:337-338` |
| Не-internal пользователь: домен сужается `_get_search_domain_share()` (только сообщения с подтипом, не internal) | `mail_message.py:341-342`, `397-398` |
| **`query = super()._search(domain, offset, limit, order, **kwargs)` — `limit` уходит в SQL ДО ACL-фильтрации** | `mail_message.py:345` |
| Далее: один SQL по построенному query, разбор строк, `author_id == pid` / `partner_id == pid` / группировка `model_ids[model][res_id]` | `mail_message.py:347-392` |
| `allowed_ids.update(self._find_allowed_doc_ids(model_ids))`, `return allowed._as_query(order)` — **страница «сжимается»** | `mail_message.py:393-395` |
| `_find_allowed_doc_ids`: по одной модели — `ir.model.access.check(model,'read')`, затем `_filter_records_for_message_operation` → `records._check_access('read')` (то есть `ir.rule` модели-источника применяются штатно) | `mail_message.py:434-456`, `400-431` |
| `_check_access('read')` — вторая линия, вызывается точечно (`toggle_message_starred`, `_get_with_access` и т. п.) | `mail_message.py:458-...`, `656` |
| `record_name` — **не хранимое** вычисляемое поле, считается `record.sudo().display_name` | `mail_message.py:115`, `245-253` |
| `record_name` попадает в клиент по умолчанию («keep for iOS app») | `mail_message.py:1140` |
| В `_to_store` каждое сообщение получает `"thread": Store.One(record, [], as_thread=True)`, а сама запись-источник кладётся в Store с `Store.Attr("display_name", sudo=True)` | `mail_message.py:1249`, `1210-1214` |
| `_order = 'id desc'` | `mail_message.py:74` |

**ПРОВЕРЕНО** (odoo shell, воспроизводимый сценарий): пользователь только с
`base.group_user` (без доступа к `crm.lead`); на лиде 20 чужих сообщений и
3 сообщения, автором которых является он сам (автор читает всегда). Результат:

```
limit=5  -> returned 3
limit=10 -> returned 3
limit=30 -> returned 3
total readable (no limit): 3
```

При `limit=5` SQL взял 5 новейших по `id DESC` (3 «свои» + 2 недоступных),
ACL оставил 3 → **страница вернула меньше запрошенного лимита**.

### 2.2. Вывод: как делаем в 19

- **Проблема 15 никуда не делась: over-fetch обязателен.** Лимит в 19
  по-прежнему применяется до ACL-фильтрации (`mail_message.py:345`), и это
  подтверждено экспериментом. Виртуальная лента партнёра — ровно тот
  случай, где ACL режет много: пользователь видит контакт, но не видит
  половину его лидов/заказов.
- **Механика over-fetch'а.** В отличие от 15, в 19 ядровый `_message_fetch`
  сам делает `self.search(domain, limit=limit)` (`mail_message.py:991`),
  поэтому «дозаписывать» страницу надо в нашей ветке ДО вызова `super()`:
  либо (а) вызывать `super()._message_fetch(..., limit=limit*K)` и
  подрезать до `limit` в нашем коде, либо (б) итеративно двигать курсор
  `before` по уже полученным id, пока не набрано `limit` или ветка не
  исчерпана. **Рекомендую (б)** с потолком итераций (5) и стартовым
  коэффициентом ×4: (а) при пользователе с очень узкими правами всё равно
  недобирает, а на широких правах впустую тянет ×4 страницы через ACL.
  Важно, чтобы дозагрузка шла **тем же `Domain`**, что и первая страница,
  и по монотонно убывающему `id` — тогда пагинация клиента остаётся
  корректной.
- **Клиентское последствие недобора.** Клиент 19 по количеству
  возвращённых сообщений выставляет `loadOlder`:
  `thread_model.js:617-625` (`fetchMoreMessages`) и `loadAround`
  (`thread_model.js:688-699`) — если пришло меньше `FETCH_LIMIT`, «ещё
  сообщений нет». Это тот же false-positive, что в 15 давал
  `isAllHistoryLoaded`, только под другими именами. Обязателен тест на
  пользователе с ограничивающим `ir.rule`.
- **`sudo()` в выборке ленты запрещён категорически.** Единственное, что
  защищает виртуальную ленту, — `mail.message._search` c его
  `_find_allowed_doc_ids` (`mail_message.py:393`, `434-456`). Любой
  `sudo().search()` (антипаттерн `velesagro_crm` из дизайна 15) отдаст
  содержимое всех заказов любому, кто видит карточку контакта.
- **Что вернёт fetch для сообщений недоступных записей: ничего.** Они
  выпадают на `_search` — ни телом, ни фактом существования, ни счётчиком
  (`res["count"]` считается `search_count` по тому же ACL-домену,
  `mail_message.py:981-982`). Требование §18.4 выполняется само.
- **Ловушка `record_name`.** Оно sudo (`mail_message.py:245-253`) и едет
  клиенту по умолчанию (`mail_message.py:1140`); то же для
  `Store.Attr("display_name", sudo=True)` записи-источника
  (`mail_message.py:1210-1214`). Для сообщений, прошедших ACL, это норма
  (иначе не нарисовать ссылку «on …»). **Инвариант:** никогда не отдавать
  клиенту «заглушки» недоступных сообщений — вместе с ними утечёт имя
  записи. Прямого аналога 15-ой ловушки `is_pinned` в 19 нет: `pinned_at`
  — обычное поле сообщения (`mail_message.py:1137`), доступ к нему
  наследует доступ к сообщению.
- **Стоимость.** `_find_allowed_doc_ids` делает по одному проходу
  `_check_access` на каждую модель, встретившуюся на странице
  (`mail_message.py:434-456`). Пёстрая партнёрская лента = 5–15
  дополнительных наборов запросов на скролл, и это умножается на
  коэффициент over-fetch'а. Замерять обязательно.

---

## 3. Клиент 19: как виртуальные сообщения попадают в тред

### 3.1. Факты

| Факт | file:line |
|---|---|
| `fetchMessages({after, around, before})`: `res = await this.fetchMessagesData(...)`; `this.store.insert(res.data)`; **`const msgs = this.store["mail.message"].insert(res.messages.reverse()); ... return msgs;`** | `thread_model.js:477-499` |
| `loadAround(messageId)`: `this.phantomMessages = this.messages;` **`this.messages = await this.fetchMessages({around: messageId});`** | `thread_model.js:669-700` (присвоение — `:680`) |
| `fetchMoreMessages`: `this.messages.unshift(...messagesToAdd)` / `.push(...)` по результату запроса | `thread_model.js:515-560` |
| `fetchNewMessages`: `this.messages.splice(startIndex, 0, ...filtered)` — тоже по результату запроса | `thread_model.js:577-625` |
| `Thread.messages = fields.Many("mail.message")` — **без `inverse`**, то есть это не вычисляемая инверсия связи «сообщение → тред» | `thread_model.js:221` |
| Поле `Message.thread` заполняется сервером записью-источником: `"thread": Store.One(record, [], as_thread=True)` | `addons/mail/models/mail_message.py:1249` |
| Ссылка «on \<документ\>»: `<small t-if="isPersistentMessageFromAnotherThread" t-on-click.prevent="openRecord" …>` → `on <a t-att-href="message.resUrl" t-esc="message.thread.displayName"/>` | `addons/mail/static/src/core/common/message.xml:48-55` (ветка «on» — `:49-51`) |
| `get isPersistentMessageFromAnotherThread()` = `!is_transient && !isPending && this.message.thread && this.message.thread.notEq(this.props.thread)` | `addons/mail/static/src/core/common/message.js:372-379` |
| Иконки статуса доставки и `incoming_email_to/cc` рисуются только при `message.thread?.eq(props.thread)` | `message.xml:194`, `:199` |
| Наш патч, скрывающий ссылку, требует `thread?.channel_kind === "record"` | `streams/static/src/core/common/message_patch.js:18-30` |
| `Thread.channel_kind` у чаттерных тредов всегда `false` (наш дефолт) | `streams/static/src/core/common/thread_model_patch.js:29-35` |

### 3.2. Вывод: как делаем в 19

**Клиентских патчей для привязки не требуется вообще.** Это главное
упрощение по сравнению с 15.

- В 15 `thread.messages` был readonly-инверсией `message.threads`, который
  считался `_computeThreads` по паре `model/res_id` — поэтому чужие
  сообщения приходилось «прописывать» в тред клиентским патчем, а
  `_computeFetchedMessages` вычищал всё, чего в `thread.messages` нет.
- В 19 `Thread.messages` — **обычное поле-список без inverse**
  (`thread_model.js:221`), и оно **заполняется прямо результатом RPC**
  (`thread_model.js:496`, присвоение `this.messages = ...` в `loadAround`,
  `thread_model.js:680`, и `push/unshift/splice` в остальных путях).
  Соответствие `model`/`res_id` треду нигде не проверяется.

Отсюда следствия, все — в нашу пользу:

1. **Виртуальные сообщения прикрепятся к треду партнёра автоматически.**
   Достаточно, чтобы сервер вернул их в `res.messages`.
2. **`Message.thread` остаётся записью-источником** (сервер кладёт туда
   `record`, `mail_message.py:1249`), `model`/`res_id` не подменяются —
   значит выполняется требование §18.1 и §18.4.
3. **Ссылка «on SO0025» рисуется бесплатно.** Условие
   `message.thread.notEq(props.thread)` (`message.js:372-379`) для
   виртуального сообщения истинно: тред — `res.partner`, источник —
   `crm.lead`. Разметка и клик уже есть (`message.xml:48-55`,
   `openRecord`).
4. **Наш `message_patch.js` ссылку в чаттере партнёра НЕ скроет.** Его
   условие начинается с `thread?.channel_kind === "record"`
   (`message_patch.js:22`), а у чаттерного треда `channel_kind === false`
   (`thread_model_patch.js:29-35`) — патч сразу проваливается в `super`.
   Проверять/менять ничего не нужно; желательно закрепить тестом Hoot.
5. **Что не будет работать (приемлемо):** у виртуальных сообщений не
   рисуются иконки статуса доставки и строки `to/cc` — оба условия
   требуют `message.thread.eq(props.thread)` (`message.xml:194`, `:199`).
   Это ровно тот же компромисс, что зафиксирован в дизайне 15 (риск про
   `message.xml:84`).
6. **Побочный эффект синглтона сохраняется**, но безвреден: одно и то же
   `mail.message` может одновременно лежать в `messages` треда партнёра и
   треда заказа — это два независимых списка, а не инверсия. Стоит
   проверить «склейку» соседних сообщений разных документов
   (`props.squashed`, `message.xml:38`) на тесте.

---

## 4. Переключатель охвата Direct / Related / Company

### 4.1. Факты

| Факт | file:line |
|---|---|
| Топбар чаттера: `<div class="o-mail-Chatter-topbar …">`, распорка `<span class="o-mail-Chatter-topbarGrow flex-grow-1 pe-2"/>`, за ней кнопка поиска | `addons/mail/static/src/chatter/web/chatter.xml:7`, `:32-35` |
| Именованный якорь для xpath: `name="chatter-topbar-left-buttons"`; классы `o-mail-Chatter-sendMessage`, `o-mail-Chatter-logNote`, `o-mail-Chatter-activity` | `chatter.xml:7-35` |
| Наш патч уже наследует `mail.Chatter` и вставляет 4 кнопки после `o-mail-Chatter-logNote` | `streams/static/src/chatter/web/chatter_patch.xml:29-60` |
| `Chatter.load(thread, requestList)` → `thread.fetchThreadData(requestList)` | `addons/mail/static/src/chatter/web_portal/chatter.js:100-104` |
| `fetchThreadData(requestList)`: если `requestList.includes("messages")` → `this.fetchNewMessages()`, затем `store.fetchStoreData("mail.thread", {...})` | `addons/mail/static/src/chatter/web_portal/thread_model_patch.js:6-16` |
| `fetchNewMessages()` при уже загруженном треде берёт `after = newestPersistentMessage.id` и **только дописывает новые** | `thread_model.js:577-625` |
| `loadAround()` без аргумента: сбрасывает `isLoaded`, прячет текущие в `phantomMessages`, целиком перезапрашивает последнюю страницу | `thread_model.js:669-700` |
| Наш `streamsReloadMessages()` = `await this.loadAround()` | `streams/static/src/core/common/thread_model_patch.js:104-107` |
| `requestList` бэкенд-чаттера: `["activities","attachments","contact_fields","followers","scheduledMessages","suggestedRecipients"]` | `addons/mail/static/src/chatter/web/chatter_patch.js:277-287` |
| Данные треда чаттера приходят из `/mail/data` → `_process_request_for_all(name == "mail.thread")` → `store.add(thread, request_list=…, as_thread=True)` | `addons/mail/controllers/webclient.py:22-28`, `:59-73` |
| `Store.add(..., as_thread=True)`: `fields = []` по умолчанию, вызывается `records._thread_to_store(self, fields, **kwargs)` | `addons/mail/tools/discuss.py:104-118` |
| `add_records_fields(..., as_thread=True)` кладёт данные в store-модель **`"mail.thread"`** с ключом `{id, model, …}` (т. е. в JS-модель `Thread`) | `addons/mail/tools/discuss.py:150-171` |
| `mail.thread._thread_to_store(store, fields, *, request_list=None)` — точка расширения; в конце `store.add(thread, res, as_thread=True)` | `addons/mail/models/mail_thread.py:5039-5097` |
| `res.partner._to_store_defaults` (mail) отдаёт `active, avatar_128, im_status, is_company, main_user_id, name` (+`email` внутренним) — **ни `parent_id`, ни `commercial_partner_id` там нет** | `addons/mail/models/res_partner.py:282-295` |
| `Thread.rpcParams` — пустой геттер, штатно расширяемая добавка к параметрам fetch-роута | `thread_model.js:458-460`, использование `:638` |

### 4.2. Вывод: как делаем в 19

**Куда встроить.** В `streams/static/src/chatter/web/chatter_patch.xml`,
`t-inherit="mail.Chatter"` — файл уже есть и уже добавляет кнопки. Ставим
**сегмент-кнопки `btn-group`** перед распоркой:
`xpath expr="//span[hasclass('o-mail-Chatter-topbarGrow')]" position="before"`.
Три `btn btn-sm` (Direct / Related / Company) с `t-att-class` для активного.
Дропдаун не нужен: вариантов три, у пользователя и так уже 6 кнопок в ряд,
а сегмент показывает текущее состояние без раскрытия. Условие показа —
`state.thread.model === 'res.partner' and state.thread.id`.

**Как перечитать ленту.** `thread.streamsReloadMessages()`, то есть
`loadAround()` (`thread_model_patch.js:104-107`). Это уже проверенный в
фазе 8 путь, и он единственно верный: `chatter.load(thread, ["messages"])`
уходит в `fetchNewMessages()` (`thread_model_patch.js:6-9`), который при
загруженном треде дописывает только сообщения новее последнего
(`thread_model.js:587-589`) и старую страницу не перечитает. Порядок:
оптимистично переключить локальное значение → `set_res_users_settings` →
`await thread.streamsReloadMessages()`; при ошибке RPC откатить значение
(схема уже отработана в `streamsSetFilters`,
`thread_model_patch.js:70-102`).

**Как понять «партнёр — физлицо без родителя».** Store для чаттерного
треда `res.partner` таких данных **не содержит**: `as_thread=True` кладёт
запись в JS-модель `Thread` (`tools/discuss.py:150-171`), а не в
`res.partner`, и набор полей там формирует `_thread_to_store`
(`mail_thread.py:5039-5097`), в который `res.partner` ничего своего не
добавляет; `res.partner._to_store_defaults` (`mail/res_partner.py:282-295`)
к треду отношения не имеет и `parent_id`/`commercial_partner_id` всё равно
не отдаёт.

**Решение:** override `res.partner._thread_to_store` в нашем модуле,
добавляющий один булев ключ треда, например
`streams_partner_has_company` = `bool(partner.parent_id)` (либо
`partner.commercial_partner_id != partner`). Плюсы: попадает ровно в тред
чаттера, не раздувает сериализацию всех партнёров-авторов и получателей,
не требует нового роута. На клиенте — `fields.Attr(false)` в нашем
`thread_model_patch.js` (реактивность; см. §5) и `t-if` на третьей кнопке.
Отдавать сам `commercial_partner_id` клиенту не надо: охват вычисляет
сервер, клиенту нужен только факт «показывать ли Company».

**Чего НЕ делать.** Не передавать выбранный охват через `rpcParams`
(`thread_model.js:458-460`): охват — персистентная настройка пользователя,
сервер обязан читать её сам, иначе тот же охват придётся дублировать в
мобильном API и в любом другом потребителе `_message_fetch`, и появится
клиентски управляемый параметр выборки.

---

## 5. `res.users.settings`: поле `streams_partner_scope`

### 5.1. Факты

| Факт | file:line |
|---|---|
| `_res_users_settings_format(fields_to_format=None)`: без списка полей форматирует **все** поля, кроме `MAGIC_COLUMNS` и чёрного списка (`_get_fields_blacklist()` = `['display_name']`) | `addons/base/models/res_users_settings.py:19-38` |
| `set_res_users_settings(new_settings)` — штатная запись: пишет только изменившиеся ключи, возвращает форматированный результат | `addons/base/models/res_users_settings.py:46-54` |
| mail-надстройка: `set_res_users_settings` дополнительно шлёт `self._bus_send("res.users.settings", formatted)` | `addons/mail/models/res_users_settings.py:34-37` |
| Первичная отдача клиенту: `_init_messaging` → `settings=settings._res_users_settings_format()` | `addons/mail/models/res_users.py:407`, `:428` |
| Пример клиентского вызова из ядра: `orm.call("res.users.settings", "set_res_users_settings", [[this.id]], {new_settings: {...}})` | `addons/mail/static/src/core/common/settings_model.js:397-411` |
| Наш прецедент: `is_streams_notify_sound_muted` объявлено только в модели, доезжает само | `streams/models/res_users_settings.py:19-21`, `streams/static/src/notify/settings_model_patch.js:15-21` |
| Наш прецедент записи с откатом при ошибке | `streams/static/src/notify/streams_notify_service_patch.js:371-384` |

### 5.2. Вывод

**Подтверждено: поедет автоматически.** Селекшн `streams_partner_scope`
(`direct`/`related`/`company`, default `related`) достаточно объявить в
`streams/models/res_users_settings.py` — `_res_users_settings_format`
сериализует все неавтоматические поля без списка
(`base/res_users_settings.py:36`), и на старте (`res_users.py:428`), и
bus-пушем после записи (`mail/res_users_settings.py:36`).

**Штатная запись** — `set_res_users_settings({'streams_partner_scope': …})`
через `orm.call` (образец `settings_model.js:397-411`; наш —
`streams_notify_service_patch.js:371-384`).

**Единственное, что надо сделать руками на клиенте** — объявить поле в
патче `Settings` (`fields.Attr("related")`), иначе owl не отследит ключ,
которого в объекте ещё нет, и сегмент-кнопки не перерисуются до первой
записи. Это ровно тот случай, который уже описан в нашем
`settings_model_patch.js:5-14`.

Сервер читает охват через хелпер (например
`res.users._streams_partner_scope()` с fallback на `related`), чтобы
`_message_fetch` не зависел от наличия записи настроек.

---

## 6. SQL VIEW в 19

### 6.1. Факты

| Факт | file:line |
|---|---|
| Канонический паттерн физической вьюхи: `_auto = False` + `init()` c `tools.drop_view_if_exists(self.env.cr, self._table)` и `CREATE OR REPLACE VIEW %s AS (...)` | `addons/crm/report/crm_activity_report.py:8-12`, `:84-92` |
| `drop_view_if_exists(cr, viewname)` умеет и `View`, и `Materialized` (через `table_kind`) | `odoo/tools/sql.py:636-641`, `TableKind` — `sql.py:225-246` |
| `init()` вызывается для **каждой модели устанавливаемого/обновляемого модуля**, сразу после `_auto_init()` | `odoo/orm/registry.py:778-779` |
| `check_tables_exist` пересоздаёт «пропавшие» таблицы вызовом `env[name].init()`; модели с `_table_query` из проверки исключены | `registry.py:981`, `:991` |
| **Альтернатива 19: `_table_query`** — SQL-выражение содержимого «таблицы», подставляемое как подзапрос; физической вьюхи нет | `odoo/orm/models.py:427`, `_table_sql` — `models.py:487-500` |
| `_table_query` как `@property` — живой паттерн 19 | `addons/purchase/report/purchase_report.py:55`, `addons/account/report/account_invoice_report.py:76`, `addons/sale/report/sale_report.py:241` |
| `_depends` — что флашить перед search/read по такой модели | `models.py:463-470` |
| **`Domain('id', 'in', SQL(...))` поддержан**: SQL-значение превращается в `Query` | `odoo/orm/domains.py:1073-1089`, `ANY_TYPES` — `:1123` |
| Рекомендованный в 19 способ вставить сырой SQL-предикат: `Domain.custom(to_sql=lambda model, alias, query: SQL(...))` | `odoo/orm/domains.py:289-300`; депрекация старого пути — `domains.py:1424-1425` |
| Удаление модели/поля при деинсталляции: `DROP TABLE %s CASCADE` / `ALTER TABLE %s DROP COLUMN %s CASCADE` | `addons/base/models/ir_model.py:345`, `:878`, `:2056` |
| `post_init_hook` вызывается **только при install**, не при upgrade | `odoo/modules/loading.py:239-243` |
| `_register_hook()` вызывается на **каждой загрузке реестра** | `odoo/orm/models.py:5819`, `odoo/modules/loading.py:588-594`, `registry.py:527` |

**ПРОВЕРЕНО** (odoo shell, от имени `base.user_admin`, `is_superuser() == False`):
UNION-ALL подзапрос (ветка `res.partner` + ветка `crm.lead`), поданный как
`Domain('id','in', SQL("SELECT v.message_id FROM (%s) v WHERE v.partner_id = %s", sub, pid))`,
проходит через кастомный `mail.message._search` и отдаёт корректный
результат:

```
related(child) -> 3 ['crm.lead', 'crm.lead', 'res.partner']
company        -> 5 ['crm.lead', 'res.partner', 'crm.lead', 'res.partner', 'res.partner']
```

Тот же домен, переданный в `_message_fetch(domain=d, thread=None, limit=30)`,
отрабатывает штатно. `Domain.custom(to_sql=…)` тоже **ПРОВЕРЕНО** рабочим.

### 6.2. GRANT-ловушка

**В наших средах не актуальна.** В `streams19` Odoo подключается как
`u_1_streams19` (не суперюзер), и **этот же роль владеет всеми таблицами**:

```
mail_message, res_partner, crm_lead, crm_activity_report -> owner u_1_streams19
```

Вьюха, созданная тем же коннектом, наследует владельца и права; отдельный
`GRANT` не нужен. Ловушка из дизайна 15 возникает, только если вьюху
создаёт один роль, а Odoo ходит другим (типично для ручных
psql-миграций на проде). **Требование к деплою:** вьюху создаёт только
модуль (в `init()`), руками в psql — никогда.

### 6.3. Вывод: как делаем в 19

Решение пользователя от 2026-08-18 («обычная SQL VIEW, не
материализованная таблица») остаётся в силе. В 19 у него есть три
исполнения; рекомендую **вариант B**.

**A. Физическая вьюха + `env.cr.execute` (буквально план дизайна 15).**
Работает, но у голого `cr.execute` есть цена: мы своими руками
воспроизводим пагинацию и, главное, **не получаем ACL** — придётся
отдельно прогонять id через `mail.message.search`, то есть всё равно
строить домен. Минус на минус.

**B. Физическая вьюха + потребление через `Domain` (рекомендуется).**
Вьюха `streams_partner_message(message_id, partner_id, commercial_partner_id)`
создаётся из реестра как `UNION ALL` веток; лента строится как

```python
Domain('id', 'in', SQL(
    "SELECT v.message_id FROM streams_partner_message v WHERE v.%s = %s",
    SQL.identifier(column), partner.id))
```

и подаётся в наш `_message_fetch` (§1). Плюсы: решение пользователя
выполнено буквально; вьюху можно `EXPLAIN`-ить и мерить (что и требуется
планом «замерить на прод-копии, порог ~300 мс»); ORM сам применяет ACL
(`mail_message.py:345-395`), пагинацию `before/after/around`
(`mail_message.py:983-991`) и наши фильтры; переиспользуемо мобильным API.
**ПРОВЕРЕНО** работоспособным на живой БД.

**Где создавать вьюху.** ORM-модель на вьюху не заводим (согласовано) —
значит вешаем создание на реестр:
`streams.partner.source.init()` (вызывается на каждом `-u streams`,
`registry.py:778-779`) + пересоздание в `create/write/unlink` реестра +
`_register_hook()` (`models.py:5819`, `loading.py:588-594`) со сверкой
сигнатуры (хеш определения) через `ir.config_parameter` — это дёшево и
закрывает три сценария разом: изменился реестр, установился/удалился
модуль-источник, вьюху снесло каскадом. `post_init_hook` для этого
непригоден — он только на install (`loading.py:239-243`).

**Обязательные предохранители при генерации SQL:**
- ветка попадает в `UNION ALL`, только если `model in self.env`, модель не
  абстрактная, `_auto` (у моделей с `_table_query` физической таблицы
  нет), таблица реально существует и колонка поля есть;
- имена таблиц/колонок — только через `SQL.identifier(...)`, никакой
  конкатенации;
- `WHERE <field> IS NOT NULL`, `JOIN res_partner p ON p.id = <field>` для
  денормализации `commercial_partner_id`;
- ветка самого партнёра (`m.model = 'res.partner'`) обязательна — иначе
  Related/Company потеряют прямую ленту.

**C. `_table_query` без физической вьюхи.** Технически чище всего (нет
объекта в БД → нет каскадных дропов и зависимостей), но требует
ORM-модель, `ir.model.access`, и SQL пересобирается на каждый запрос.
Держим как запасной путь, если риск 6.4 окажется болезненным.

### 6.4. Специфический риск физической вьюхи в 19

Обычная (не materialized) вьюха создаёт **жёсткую зависимость PostgreSQL**
на таблицы и колонки источников. При деинсталляции модуля-источника Odoo
делает `DROP TABLE ... CASCADE` (`ir_model.py:345`, `:2056`), при удалении
поля — `ALTER TABLE ... DROP COLUMN ... CASCADE` (`ir_model.py:878`).
CASCADE означает, что **нашу вьюху молча снесут**, и лента партнёра
сломается до следующего пересоздания. Именно поэтому пересоздание должно
висеть в том числе на `_register_hook` (перезагрузка реестра происходит
сразу после деинсталляции), а код чтения — терпимо реагировать на
отсутствие вьюхи (проверка `sql.table_kind`, `sql.py:234`, и
fallback «только Direct» с логом).

---

## 7. Реестр `streams.partner.source`

### 7.1. Что реально есть в `streams19`

Установлено 48 модулей; из релевантных — `crm`, `calendar`, `contacts`,
`sales_team`, `sms`, `snailmail`, `queue_job`, `streams`, `streams_mobile`.
**`sale`, `purchase`, `account`, `stock` не установлены.**

Запрос кандидатов (m2o → `res.partner`, `store`, на моделях с
`message_ids`) на живой БД даёт всего:

```
crm.lead     partner_id       store=t  related=
res.partner  commercial_partner_id  store=t
res.partner  parent_id        store=t
res.users    partner_id       store=t
```

**Вывод для тестов:** единственная реальная «чужая» модель для проверки
агрегации в этой среде — **`crm.lead.partner_id`**, плюс сам `res.partner`
как ветка Direct. Этого достаточно и для Related, и для Company (через
`parent_id` → `commercial_partner_id`): сценарий «компания + контакт +
лид на контакте» **ПРОВЕРЕН** в §6.1 и дал ожидаемые 3/5 сообщений.
Модели `mail.test.*` недоступны — модуль `test_mail` не установлен;
поднимать его ради фикстур не нужно, `crm` покрывает и m2o-ветку, и
цепочку `commercial_partner_id`.

### 7.2. Валидация поля реестра

Модель `streams.partner.source` (`model_id` m2o `ir.model`, `field_id` m2o
`ir.model.fields`, `active`). Проверять в `@api.constrains` по данным
`ir.model.fields`:

- `field_id.ttype == 'many2one'` и `field_id.relation == 'res.partner'`;
- `field_id.store` — нехранимое поле колонки не имеет, ветка SQL
  невозможна;
- `field_id.model_id == model_id` (консистентность пары);
- модель — mail.thread: есть поле `message_ids` с `relation='mail.message'`
  (в 19 у `ir.model` нет флага «это mail.thread», а проверка по
  `_inherit` не ловит косвенное наследование);
- модель не абстрактная и `_auto` (иначе физической таблицы нет —
  ср. `_table_query`, `models.py:427`);
- **предупреждение, а не запрет**, если `field_id.related` заполнено:
  related-зеркало почти всегда дублирует уже учтённое поле и удваивает
  ленту (решение 4 от 2026-08-18 — такие поля в дефолт не включаем);
- `UNIQUE(model_id, field_id)`.

Дополнительно осмысленно предупреждать, если поле указывает на партнёра
собственной компании (сверка с `res.company.partner_id`) — типовая
причина мусора в ленте по опыту дизайна 15.

### 7.3. Сидирование только для установленных моделей

XML-`data` с `ref` на `ir.model` чужого модуля упадёт, если модуль не
установлен, а `streams` от `sale`/`crm` не зависит и зависеть не должен.

**Как делаем:** сид — хук-ориентированный. Таблица дефолтов живёт в Python
(`{'sale.order': ['partner_id'], 'crm.lead': ['partner_id'], …}`), а
применяется идемпотентно в `streams.partner.source.init()` (вызывается на
каждом `-u streams`, `registry.py:778-779`) — создаются строки только для
моделей, присутствующих в `self.env` и прошедших валидацию §7.2; уже
существующие строки не трогаются (пользователь мог их деактивировать).
`post_init_hook` для этого не подходит: он вызывается только при install
(`loading.py:239-243`), а модули-источники ставят и позже.

Сценарий «`sale` установили после `streams`» закрывается двумя вещами:
(1) `_register_hook` (`models.py:5819`, `loading.py:588-594`) сверяет
сигнатуру вьюхи и пересобирает её; (2) в UI реестра — действие
**«Найти кандидатов»**, показывающее незарегистрированные m2o-поля по
запросу вида

```sql
SELECT f.model, f.name, f.field_description, f.related
  FROM ir_model_fields f
 WHERE f.ttype = 'many2one' AND f.relation = 'res.partner' AND f.store
   AND f.model IN (SELECT model FROM ir_model_fields
                    WHERE name = 'message_ids' AND relation = 'mail.message')
 ORDER BY f.model, f.name
```

(этот запрос **ПРОВЕРЕН** на `streams19`, вывод — в §7.1).

### 7.4. Предпросмотр («сколько сообщений добавит запись реестра»)

Отдельного механизма в 19 нет и не нужно: ветка реестра — это тот же
`Domain('id','in', SQL(branch))`, значит счётчик — это
`self.env['mail.message'].search_count(branch_domain)` (при желании — с
`sudo()` для админского предпросмотра, поскольку это оценка объёма, а не
выдача содержимого; в этом случае обязательно не показывать ни одного
сообщения, только число). Считать до сохранения записи реестра можно тем
же кодом, что генерирует ветку вьюхи, — генератор SQL должен быть
отдельной функцией от «записан ли реестр».

---

## 8. Наши инварианты: канал партнёра и фильтр потоков фазы 8

### 8.1. Канал партнёра не затрагивается

| Факт | file:line |
|---|---|
| `_streams_link_existing_channels` линкует сообщение только к каналу **своей** пары `(message.model, message.res_id)`: домен строится по `targets` из самих сообщений, сопоставление — `channel_by_target.get((message.model, message.res_id))` | `streams/models/mail_message.py:184-223` (ключевое — `:199-200`, `:212-220`) |
| `_streams_attach_history` — сырой SQL строго `WHERE msg.model = %s AND msg.res_id = %s` (значения — `self.res_model`, `self.res_id` канала) | `streams/models/discuss_channel.py:88-106` (`:99-104`) |
| `_streams_message_domain` канала — только `model='discuss.channel' AND res_id IN self.ids` ИЛИ `stream_channel_ids IN self.ids` | `streams/models/discuss_channel.py:515-521` |
| `_get_last_messages` — по тем же двум источникам | `streams/models/discuss_channel.py:523-546` |

**Вывод:** канал `res.partner` подшивает и показывает исключительно
сообщения с `model='res.partner'` и своим `res_id`. Виртуальная
агрегация живёт только в домене `_message_fetch` и **не создаёт ни одной
строки** в `mail_message_stream_channel_rel`. §18.5 выполняется без правок.
Инвариант обязателен к закреплению тестом: «сообщение лида не появляется
в `stream_channel_ids` канала партнёра».

### 8.2. Серверный фильтр потоков (решение Р1 фазы 8) виртуальную ленту не тронет

`streams/models/mail_message.py:375-384`:

```python
if thread is not None and thread._name == 'discuss.channel' \
        and len(thread) == 1 and thread.channel_kind:          # :375-376
    projection = thread._streams_message_domain() & ...        # :377-378
    if thread.channel_kind == 'record' \
            and not self.env.context.get('streams_unfiltered'):  # :379-380
        projection &= self._streams_filters_domain(thread)      # :381
```

Вход в ветку требует `thread._name == 'discuss.channel'` (`:375`), а
фильтры потоков — дополнительно `channel_kind == 'record'` (`:379`). У
чаттера партнёра `thread._name == 'res.partner'` — обе проверки
проваливаются, `_streams_filters_domain` не применяется.

Это, к слову, **сознательный пробел, который надо закрыть в фазе 9**:
§18.4 требует, чтобы виртуальные `change` в агрегированную ленту не
попадали. Раз фильтр канала не срабатывает, отсечение `change` (и
«прочего») для **чужих** моделей делается прямо в
`_streams_partner_domain`: `& ~self._streams_stream_domain(STREAM_CHANGE)`
для виртуальной части, при этом ветка самого партнёра (`model='res.partner'`)
остаётся без этого ограничения — изменения по самому партнёру показываются
как раньше (§18.4). `_streams_stream_domain` уже есть и уже сверен с
классификатором тестом (`streams/models/mail_message.py:306-338`).

---

## Сводка решений для 19

1. **Врезка — в наш форк `mail.message._message_fetch`**, ветка
   `thread._name == 'res.partner'`, а не override роута. Роут 19 сам
   проверяет доступ к треду (`thread.py:63`) и передаёт `thread`
   recordset'ом (`thread.py:64`) — оба довода дизайна 15 в пользу роута
   отпали; форк у нас уже есть.
2. **Охват читает сервер** из `res.users.settings.streams_partner_scope`.
   Клиент охват в запросе не передаёт (никакого `rpcParams`).
3. **Домен вместо сырого SQL-курсора:**
   `Domain('id','in', SQL("SELECT message_id FROM streams_partner_message WHERE …"))`
   — тогда ACL, пагинация `before/after/around` и `count` достаются
   бесплатно от ядра. ПРОВЕРЕНО на живой БД, включая не-суперюзера.
4. **Хранилище — обычная SQL VIEW** (решение пользователя в силе),
   генерируемая из реестра. Создание/пересоздание: `init()` модели реестра
   + `create/write/unlink` реестра + сверка сигнатуры в `_register_hook`.
   ORM-модель на вьюху не заводим.
5. **`sudo()` в выборке ленты — запрещён.** Единственная защита —
   `mail.message._search` (`mail_message.py:345-395`).
6. **Over-fetch обязателен** (лимит применяется до ACL,
   `mail_message.py:345`; ПРОВЕРЕНО: `limit=5` → 3 сообщения). Реализация
   — итеративное движение курсора `before` в нашей ветке, ≤5 итераций,
   старт ×4.
7. **Клиентских патчей привязки не нужно.** `Thread.messages` в 19 —
   список без inverse, заполняемый результатом RPC
   (`thread_model.js:221`, `:496`, `:680`). `Message.thread` остаётся
   записью-источником (`mail_message.py:1249`), ссылка «on \<doc\>»
   рисуется ядром (`message.xml:48-55`).
8. **Наш `message_patch.js` ссылку не скроет** — его условие требует
   `channel_kind === "record"` (`message_patch.js:22`), у чаттерного треда
   это `false`. Закрепить Hoot-тестом.
9. **Переключатель** — `btn-group` из трёх кнопок в
   `chatter_patch.xml`, xpath `//span[hasclass('o-mail-Chatter-topbarGrow')]`
   `position="before"`; перечитка ленты — `thread.streamsReloadMessages()`
   (`loadAround()`), не `chatter.load(...,["messages"])`.
10. **Признак «физлицо без родителя»** — свой булев ключ треда через
    override `res.partner._thread_to_store` (`mail_thread.py:5039-5097`);
    штатный Store партнёра `parent_id`/`commercial_partner_id` не отдаёт
    (`mail/res_partner.py:282-295`).
11. **`streams_partner_scope` поедет клиенту сам**
    (`base/res_users_settings.py:36`), запись — `set_res_users_settings`
    (`:46-54`, bus-пуш `mail/res_users_settings.py:36`); на клиенте
    объявить `fields.Attr` ради реактивности.
12. **Сид реестра — хук-ориентированный** (`init()` модели реестра),
    не XML-data: `post_init_hook` только на install
    (`loading.py:239-243`), а `sale`/`crm` могут ставиться позже.
13. **Отсечение виртуальных `change`** делается в
    `_streams_partner_domain` через `~_streams_stream_domain('change')`
    для чужих моделей: канальный фильтр потоков на чаттер партнёра не
    распространяется (`streams/models/mail_message.py:375-381`).
14. **Тестовая база — `crm.lead.partner_id`**: в `streams19` это
    единственная сторонняя m2o-ветка (`sale`/`purchase`/`account` не
    установлены).

---

## Риски

1. **Недобор страницы при узких правах.** Лимит до ACL
   (`mail_message.py:345`) + пороги `loadOlder` на клиенте
   (`thread_model.js:617-625`, `:688-699`) дают ложное «истории больше
   нет». Over-fetch снижает вероятность, но не устраняет: 5 итераций может
   не хватить пользователю, которому видно 1% записей. **Тест на
   пользователе с ограничивающим `ir.rule` обязателен.**
2. **Стоимость ACL на пёстрой ленте.** `_find_allowed_doc_ids`
   (`mail_message.py:434-456`) прогоняет `_check_access` по каждой модели
   страницы; при over-fetch ×4 и 10 моделях это десятки наборов запросов
   на скролл. Мерить вместе с вьюхой, а не после.
3. **Каскадный снос вьюхи.** `DROP TABLE ... CASCADE` /
   `ALTER TABLE ... DROP COLUMN ... CASCADE` при деинсталляции модуля или
   удалении поля (`ir_model.py:345`, `:878`, `:2056`) молча удалят
   `streams_partner_message`. Нужны: пересоздание в `_register_hook`,
   проверка `sql.table_kind` перед использованием и деградация в Direct с
   логом вместо traceback.
4. **Производительность самой вьюхи.** Это и есть предмет замера,
   заложенный в решении от 2026-08-18: `UNION ALL` из N веток + сортировка
   `id DESC` + `LIMIT` — стоимость растёт с размером партнёра. Порог
   эскалации к материализованной таблице — ~300 мс на страницу; интерфейс
   генерации домена держать одной функцией, чтобы замена была локальной.
5. **Ошибочная запись реестра.** Поле, означающее нашу компанию или
   служебную сторону, немедленно засоряет ленту всех партнёров и, что
   хуже, требует пересоздания вьюхи для отката. Валидация §7.2 +
   предпросмотр §7.4 — не украшение, а страховка.
6. **Утечка через `record_name`/`display_name`.** Оба sudo
   (`mail_message.py:245-253`, `:1210-1214`) и едут клиенту по умолчанию
   (`:1140`). Безопасно ровно до тех пор, пока мы не отдаём клиенту ничего
   про сообщения, не прошедшие ACL. Никаких «N скрытых сообщений».
7. **`set_message_done` на чаттерном роуте.** `thread.py:65-66` гасит
   needaction по **всем** отданным сообщениям — включая виртуальные, с
   чужих записей. Это прямо противоречит §18.4 («не гасит уведомления
   чужих записей») и §18.6. Ловушка неочевидная: она в роуте, а не в
   `_message_fetch`, поэтому наша врезка её не видит. **Требует решения
   на этапе дизайна фазы 9** — вероятнее всего, override роута всё-таки
   понадобится, но только ради `set_message_done` (сужать до сообщений с
   `model == 'res.partner' and res_id == thread.id`), а не ради выборки.
8. **Мобильное API.** `streams_mobile` ходит в `_message_fetch` со своим
   контрактом; партнёрская ветка изменит выдачу чаттера партнёра и для
   него. Проверить `api-v1.md` и тесты `streams_mobile` до релиза; при
   необходимости — контекстный флаг по образцу `streams_unfiltered`
   (`streams/models/mail_message.py:380`).
9. **Squash соседних сообщений разных документов.** Лента партнёра
   перемешивает источники; `props.squashed` (`message.xml:38`) может
   склеить два сообщения одного автора с разных записей, спрятав шапку со
   ссылкой «on \<doc\>». Проверить визуально и, при необходимости,
   запретить squash при смене `message.thread`.
