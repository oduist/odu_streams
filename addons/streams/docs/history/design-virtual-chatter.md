Both research agents have reported. Here is the deliverable.

---

# ЧАСТЬ 1 — Раздел для `docs/roadmap.md`

> Вставить как новый раздел после §13 (или перед §14 «Настройки продукта»), нумерация — на усмотрение владельца документа.

## 18. Виртуальный чаттер партнёра (планируется)

### 18.1. Идея

Чаттер `res.partner` перестаёт быть лентой сообщений «по самой карточке контакта» и становится **агрегатором**: показывает сообщения всех записей, связанных с этим контрагентом — лидов, заказов на продажу и закупку, счетов, поставок, транспортных заказов, писем MessageBox и т. д.

Агрегация — не копирование. Сообщение по-прежнему существует в единственном экземпляре и лежит на своей записи-источнике (`model`/`res_id` не подменяются). Чаттер партнёра — ещё одна **проекция** тех же `mail.message`, как канал записи в §3.

### 18.2. Три уровня охвата

| Уровень | UI-подпись | Что показывает |
|---|---|---|
| Прямой | **Direct** | только сообщения самой записи `res.partner` |
| Связанный | **Related** | прямой + сообщения всех записей, где этот контакт указан как контрагент |
| Компания | **Company** | связанный уровень для всех контактов организации (`commercial_partner_id`) |

Переключатель — в шапке чаттера партнёра, рядом с кнопками §11.1. Выбор персистентный per-user (не per-record), как фильтры потоков §6.

Для контакта-физлица без родителя уровни Related и Company совпадают. Для контакта внутри компании Company поднимает выборку до всей организации: сообщения по заказам, оформленным на другой контакт той же компании, видны и здесь.

### 18.3. Что считается «связанной записью»

Связь описывается **явным реестром** «модель → поле-ссылка на партнёра», а не автоматическим сканированием всех m2o-полей на `res.partner`. Реестр — редактируемая таблица (Settings → Technical), поставляется с начальным наполнением: `sale.order`, `purchase.order`, `account.move`, `crm.lead`, `stock.picking`, `supply.shipment`, `supply_contract.contract`, `transport.order`, `transport.loading`, `coa.order`/`coa.sampling`/`coa.redeem_lot`, `email.document`, `ksef.invoice`, `connect_messagebox.message`, `project.task`, `account.analytic.account`.

Автоматический режим не используется намеренно: у моделей есть m2o на партнёра, означающие не контрагента, а нашу собственную компанию (`supply.shipment.recipient`, `transport.order.requester`, `hr.contract.our_company_id`), служебную сторону (`coa.order.lab`, `transport.order.checkpoint`, `customs_clearance`) или зеркала уже учтённых полей (`ksef.invoice.to_client`, `supply.shipment.t_o_client`). По коду таких полей ~95–100 на ~55 моделях; без ручной курации лента забивается мусором и дублями.

Модели, у которых прямой ссылки на партнёра нет, но связь есть через промежуточную запись (`cmr`, `supply.doc`, `supply.settlement` — через `shipment_id`), подключаются переопределением хук-метода на самой модели, а не записью в реестре.

### 18.4. Правила видимости

- Пользователь видит в агрегированной ленте **только сообщения тех записей, которые ему разрешено читать**. Проверка — штатная, по правам записи-источника; лента не выполняется от имени администратора. Сообщение недоступного заказа не показывается вовсе — ни телом, ни фактом существования.
- Каждое виртуальное сообщение подписано ссылкой на запись-источник («on SO0025») — ссылка кликабельна и открывает запись. Для сообщений самого партнёра подписи нет.
- Виртуальные **изменения** (`change`) и служебные сообщения «прочее» в агрегированную ленту не попадают: их место — в чаттере и канале самой записи. Изменения по самому партнёру показываются как раньше, по фильтру §6.
- Уровни Related и Company не влияют на счётчик непрочитанных партнёра и на его канал.

### 18.5. Канал партнёра остаётся реальным

Канал Discuss для `res.partner` создаётся и работает по общим правилам §5: лениво, при первом комментарии/заметке/сообщении/активности, подшивает историю **только самой карточки партнёра**. В канале партнёра видны исключительно реальные сообщения по партнёру; агрегация живёт только в чаттере. Сообщение лида или заказа никогда не связывается с каналом партнёра.

Сообщение, написанное в чаттере партнёра, публикуется на самом партнёре — стандартно, без спец-обработки: попадает в канал партнёра и в его прямую ленту.

### 18.6. Чего функция не делает

- Не переносит и не копирует сообщения между записями.
- Не даёт писать «в контекст заказа» из чаттера партнёра: ответ на виртуальное сообщение делается на записи-источнике, по ссылке.
- Не агрегирует активности, вложения, followers и подписки на поля — они остаются пер-запись.
- Не отмечает прочитанными уведомления по чужим записям при просмотре ленты партнёра.
- Не строит рекурсивную агрегацию «партнёр → его заказы → их поставки»: учитывается только прямая связь записи с партнёром (плюс явно описанные хопы §18.3).

---

# ЧАСТЬ 2 — Технический дизайн (черновик)

## A. Карта фактов

### A.1. Путь чаттера к ленте (ядро)

| Факт | file:line |
|---|---|
| Роут чаттера `/mail/thread/messages`, домен `[('res_id','=',id),('model','=',model),('message_type','!=','user_notification')]`, **никакой проверки прав на запись-тред** | `~/Dev/odoo_15/addons/mail/controllers/discuss.py:424-430` |
| Роут канала `/mail/channel/messages` (работает в sudo-env, компенсируя жёстко зашитым `model='mail.channel'`) | `.../controllers/discuss.py:384-391` |
| `_message_fetch(domain, max_id, min_id, limit=30)` → `AND [('id','<',max_id)]` / `[('id','>',min_id)]` → `self.search(domain, limit).message_format()` | `.../models/mail_message.py:899-912` |
| `_message_format`: `check_access_rule('read')` — единственная явная проверка; далее `_read_format` (в обход `read()`) | `.../mail_message.py:827-829` |
| `record_name` считается **sudo** из записи-источника | `.../mail_message.py:859-867` |
| Список полей JSON: `model, res_id, record_name, …` | `.../mail_message.py:975-983` |
| `_search` override: суперюзер → ранний выход без фильтрации | `.../mail_message.py:271-274` |
| `_search`: `limit` применяется **до** ACL-фильтрации → страница «сжимается» | `.../mail_message.py:279-281` |
| `_search`: доступ через документ-источник, по одному `search` на модель | `.../mail_message.py:313-314`, `326-330`, `332-339` |
| `check_access_rule('read')`: author / recipient / needaction / права на документ | `.../mail_message.py:341-553` (`480-507`) |
| `_order = 'id desc'` | `.../mail_message.py:69` |
| Индексы: `model` index, `res_id` index, композит `mail_message_model_res_id_idx (model, res_id)` в `init()` | `.../mail_message.py:103`, `104`, `249-252` |
| needaction живёт в `mail_notification` (покрывающий индекс `res_partner_id, is_read, notification_status, mail_message_id`) | `.../mail_notification.py:19,22,34,57-62` |
| `mark_all_as_read(domain)` — через `search`, права учитываются; `set_message_done` гасит только собственные нотификации | `.../mail_message.py:713-736`, `738-757` |

### A.2. Клиент (ядро)

| Факт | file:line |
|---|---|
| `convertData`: `originThread = insertAndReplace({id: res_id, model, name: record_name})` — **тред определяется исключительно парой model/res_id из JSON** | `.../static/src/models/message/message.js:84-99` |
| `_computeThreads` — единственный источник `message.threads`; `thread.messages` — его readonly-инверсия | `message.js:604-618`, поля `:831-833`, `:858-861` |
| `_computeFetchedMessages` unlink-ает всё, чего нет в `thread.messages` | `thread_cache.js:79-90` |
| `_loadMessages` шлёт `{...fetchMessagesParams, limit, max_id, min_id}` | `thread_cache.js:219-254` |
| **`if (!minId && messages.length < limit) isAllHistoryLoaded = true`** | `thread_cache.js:247-249` |
| Пагинация: `maxId = Math.min(fetched ids)`, `minId = Math.max(fetched ids)` | `thread_cache.js:30`, `:61` |
| `_onChangeMarkAllAsRead` → домен `[['model','=',thread.model],['res_id','=',thread.id]]` | `thread_cache.js:278-302` |
| URL/params ленты: не-канал → `/mail/thread/messages`, `{thread_id, thread_model}` | `thread.js:1442-1455`, `1425-1436` |
| `thread.url` = `#model=<model>&id=<id>` — ссылка «on SO0025» работает из коробки | `thread.js:1892-1898` |
| Шаблон «on \<document\>» / «(from #channel)», кликабельный | `components/message/message.xml:111-119` |
| Иконка статуса доставки показывается только когда `originThread === threadView.thread` | `message.xml:84` |
| Старт загрузки ленты чаттера | `chatter.js:230-274` (`:252-254`) |

### A.3. Прецедент velesagro_crm

| Факт | file:line |
|---|---|
| Детектор «это чаттер лида»: требует, чтобы **все** термы домена были 3-элементными списками | `addons_veles/velesagro_crm/models/mail_message.py:16-44` (`18-20`) |
| Override `_message_fetch`, `check_access_rights/rule` на лиде, вырезание model/res_id термов, `AND` с доменом лида, ручной `max_id`/`min_id` | `.../mail_message.py:46-77` |
| **`self.sudo().search(...)`** — ACL `mail.message._search` полностью обходится | `.../mail_message.py:78-79` |
| Подмена `model`/`res_id`/`record_name` в готовом JSON | `.../mail_message.py:80-90` |
| Домен склейки на лиде | `addons_veles/velesagro_crm/models/crm_lead.py:84-101` |

### A.4. Модуль streams

| Факт | file:line |
|---|---|
| m2m `stream_channel_ids` + таблица `mail_message_stream_channel_rel` | `addons_veles/streams/models/mail_message.py:23`, `45-47` |
| `_streams_link_existing_channels` — линкует **только** по своей паре (model,res_id) | `.../mail_message.py:120-160` |
| Классификатор потоков | `.../mail_message.py:80-114` |
| `_message_format` добавляет `stream_channel_ids`, `streams_kind` | `.../mail_message.py:166-175` |
| `_streams_attach_history` — SQL по `msg.model = res_model AND msg.res_id = res_id` | `.../mail_channel.py:87-105` |
| `_streams_message_domain` канала | `.../mail_channel.py:245-250` |
| `channel_info` расширяется своими ключами | `.../mail_channel.py:142-164` |
| Override роута `/mail/channel/messages` (с пустым `@http.route()`) | `.../controllers/discuss.py:13-30` |
| JS: патч `_computeThreads` добавляет каналы из `streamChannels` | `.../static/src/models/message.js:46-77` (`67-76`) |
| JS: `convertData` читает `streams_kind` / `stream_channel_ids` | `.../static/src/models/message.js:26-44` |
| JS: `thread.js` — `streamsChannelKind/ResModel/ResId/Filters` | `.../static/src/models/thread.js` |
| Скрытие ссылки «on \<doc\>» **только** в канале своей записи | `.../static/src/xml/message.xml` (xpath по `o_Message_originThread`) |
| Чёрный список моделей для каналов (в т. ч. `connect_messagebox.message`) | `.../models/mail_thread.py:16-21` |
| `res.users.settings` как канал доставки персональных настроек в `init_messaging` | `.../models/res_users_settings.py` |

### A.5. Партнёр и реестр связей

| Факт | file:line |
|---|---|
| `commercial_partner_id`: **store=True, index=True**, рекурсивно поднимается до верхней компании | `~/Dev/odoo_15/odoo/addons/base/models/res_partner.py:233-235`, `340-346` |
| `parent_id` (index), `child_ids` (только активные) | `res_partner.py:164`, `166` |
| Прецедент «партнёр + его коммерческая сущность» в репозитории | `addons_veles/velesagro_crm/models/connect_messagebox_message.py:83` |
| `connect_messagebox.message.matched_partner_id` — computed **store=True**, матч по `sender_address` | `.../connect_messagebox_message.py:49-65` |

**Главные модели/поля, которые должны попасть в реестр** (сокращённо; полная таблица — в результатах скана):

- Ядро: `sale.order.partner_id` (+`partner_invoice_id`, `partner_shipping_id`), `purchase.order.partner_id`, `account.move.partner_id`, `crm.lead.partner_id`, `stock.picking.partner_id`, `project.task.partner_id`, `account.analytic.account.partner_id`, `purchase.requisition.vendor_id`.
- `addons_veles`: `supply.shipment.company_partner_id` (related на `supply.company.partner`, store=True), `supply_contract.contract.partner_id`, `supply_contract.production_plan.partner_id`, `transport.order.client` / `forwarder` / `forwarder_contact`, `transport.loading.client`, `coa.order.lab`(?), `coa.sampling.customer_id`, `coa.redeem_lot.partner_id`, `sale.lot.partner_id`, `email.document.vendor`, `ksef.invoice.partner_id`, `revolut.invoice.partner_id`, `mrp.production.customer`, `connect_messagebox.message.matched_partner_id`.
- **Исключить:** `supply.shipment.recipient`, `transport.order.requester`, `hr.contract.our_company_id` (наша компания); `transport.order.checkpoint/customs_clearance/driver`, `coa.order.lab` (служебные стороны — решение владельца); все related-зеркала (`ksef.invoice.to_client/to_forwarder/shipment_supplier/clo_supplier`, `supply.shipment.t_o_client/t_o_forwarder/sale_order_partner/recipient_partner_company`, `email.document.vendor_commercial_id`, `purchase.order.shipment_recipient`) — иначе те же записи попадут в ленту повторно через другой ключ.

Runtime-перечисление кандидатов (для админ-UI реестра):

```sql
SELECT f.model, f.name, f.field_description, f.related
FROM ir_model_fields f
WHERE f.ttype = 'many2one' AND f.relation = 'res.partner' AND f.store
  AND f.model IN (SELECT model FROM ir_model_fields
                  WHERE name = 'message_ids' AND relation = 'mail.message')
ORDER BY f.model, f.name;
```

(в Odoo 15 у `ir.model` нет флага mail.thread; детект через наличие `message_ids` ловит и косвенное наследование `mail.thread.cc`, в отличие от проверки `'mail.thread' in _inherit`).

---

## B. Рекомендуемая архитектура

### B.1. Ключевое решение №1 — материализованный индекс, а не OR-домен

**Не** строить домен вида `OR([('model','=',m),('res_id','in',ids)] for m in models)`.

Почему: у крупной компании это тысячи пар. Индекс на `mail_message` — `(model, res_id)` без `id` в хвосте (`mail_message.py:249-252`), поэтому `ORDER BY id DESC LIMIT 30` поверх BitmapOr по тысячам пар превращается в сортировку десятков тысяч строк — и так на **каждый скролл**. Плюс расходы на предварительный сбор `res_id` по 15+ моделям на каждой странице.

**Новая модель-индекс** (реальная таблица, не m2m-поле):

```
streams.message.partner
  message_id             m2o mail.message  ondelete='cascade'
  partner_id             m2o res.partner   ondelete='cascade'
  commercial_partner_id  m2o res.partner   ondelete='cascade'   # денормализация
  source_model           char                                   # для перестройки/отладки
  source_res_id          integer
```

Индексы:
```sql
UNIQUE (message_id, partner_id)
INDEX  (partner_id, message_id DESC)
INDEX  (commercial_partner_id, message_id DESC)
```

Индексируются **все** сообщения, включая сообщения самой карточки партнёра (`source_model='res.partner'`) — тогда лента на любом уровне охвата — один запрос без OR с «реальным» доменом, а `UNIQUE` снимает дубли, когда два зарегистрированных поля одной записи указывают на одного партнёра (`sale.order.partner_id == partner_invoice_id`).

Выборка страницы:

```sql
SELECT message_id FROM streams_message_partner
 WHERE commercial_partner_id = %s      -- либо partner_id = %s для Direct/Related
   AND message_id < %s                 -- max_id
 ORDER BY message_id DESC LIMIT %s
```
— index-only scan, стоимость O(limit) вне зависимости от того, 50 у партнёра сообщений или 500 000. Именно ради уровня Company денормализован `commercial_partner_id`: вариант «`partner_id IN (подзапрос по контактам компании)`» даёт BitmapOr по сотне контактов и сортировку, что заметно хуже.

`change` и «прочее» (`streams_kind` false) в виртуальной части отсекаются **на этом же запросе** — храним в таблице `streams_kind` копией (char) либо просто не индексируем такие сообщения для чужих моделей. Рекомендую хранить: дешевле, чем перестраивать при смене политики.

### B.2. Ключевое решение №2 — НЕ подменять `model`/`res_id` в JSON

Прецедент velesagro_crm (`mail_message.py:80-90`) для партнёра воспроизводить нельзя, три причины:

1. `mail.message` на клиенте — **синглтон по id** (`message.js:84-98`, `insertAndReplace`). Подмена перезапишет `originThread` в общем сторе: сообщение по SO, открытое одновременно в чаттере SO или в record-канале SO в Discuss, «переедет» в тред партнёра и исчезнет оттуда (`thread_cache.js:79-90` его отлинкует). Для messagebox-сообщений это редкость, для заказов — норма.
2. Подмена **убивает** ровно тот UI, который здесь требуется: ссылка «on SO0025» (`message.xml:111-119`) рисуется по `originThread` и после подмены исчезнет.
3. Подмена не даёт никаких прав — она чистая клиентская фикция; вся защита теряется в момент `sudo()`, а не подмены.

Вместо этого — **переиспользовать уже построенный в фазе 1b механизм проекций**: сервер кладёт в JSON дополнительный ключ, клиент патчит `_computeThreads`.

Сервер (наш роут):
```python
values['streams_virtual_thread'] = {'model': 'res.partner', 'id': partner.id}
```
Клиент — дополнение существующего патча `streams/static/src/models/message.js:46-77`:
```js
// convertData: streamsVirtualThread = insert({model, id})
// _computeThreads: threads.push(this.streamsVirtualThread)
```
`originThread` остаётся `sale.order` → ссылка «on SO0025» рендерится и кликается (`thread.url`, `thread.js:1892-1898`), существующий xpath-скрыватель ссылки (`streams/static/src/xml/message.xml`) не срабатывает, потому что условие завязано на `streamsChannelKind === 'record'`, а чаттер партнёра — не канал. UI-требование №4 выполняется без единой строки шаблона.

### B.3. Ключевое решение №3 — override роута, а не `_message_fetch`

Ветвление делать в `streams/controllers/discuss.py` (там уже есть образец с обязательным пустым `@http.route()` — `discuss.py:13`):

```python
@http.route()
def mail_thread_messages(self, thread_model, thread_id, max_id=None, min_id=None,
                         limit=30, **kwargs):
    if thread_model != 'res.partner':
        return super().mail_thread_messages(...)
    scope = request.env.user.res_users_settings_id.streams_partner_scope  # direct/related/company
    if scope == 'direct':
        return super().mail_thread_messages(...)
    partner = request.env['res.partner'].browse(int(thread_id))
    partner.check_access_rights('read'); partner.check_access_rule('read')
    return request.env['mail.message']._streams_partner_feed(
        partner, scope, max_id=max_id, min_id=min_id, limit=limit)
```

Плюсы против override `_message_fetch`:
- не нужен хрупкий детектор формы домена;
- **полностью снимается вопрос MRO с velesagro_crm** (см. §C.4);
- ядровый роут `/mail/thread/messages` (`discuss.py:424-430`) вообще не проверяет прав на тред — мы добавляем явную проверку партнёра, чего в ядре нет.

### B.4. Права доступа — обязательный не-sudo путь

```python
@api.model
def _streams_partner_feed(self, partner, scope, max_id, min_id, limit):
    result, cursor = [], max_id
    for _ in range(5):                       # ограничитель итераций
        ids = self.env['streams.message.partner']._page(
            partner, scope, max_id=cursor, min_id=min_id, limit=limit * 4)
        if not ids:
            break
        # НЕ sudo: ACL mail.message._search отфильтрует по правам записей-источников
        result += self.search([('id', 'in', ids)]).ids
        cursor = ids[-1]
        if len(result) >= limit:
            break
    return self.browse(result[:limit]).message_format()
```

- `_search` (`mail_message.py:313-339`) сам сгруппирует id по моделям и выполнит по одному `search` на модель с учётом `ir.rule` — то есть **`ir.rule` каждой модели-источника применяется штатно**. Дополнительных проверок писать не надо, но и `sudo()` использовать нельзя ни на шаг.
- `message_format` вызовет `check_access_rule('read')` (`mail_message.py:828`) — вторая линия.
- **Over-fetch (`limit * 4`) обязателен** из-за `mail_message.py:279-281`: лимит применяется до ACL-фильтрации, страница «сжимается», а клиент на `messages.length < limit` ставит `isAllHistoryLoaded = true` (`thread_cache.js:247-249`) и перестаёт подгружать историю. Без over-fetch у пользователя с ограниченными правами лента будет обрываться в случайном месте.
- Пагинация корректна: `mail.message.id` глобален, клиент листает по `min/max` из уже полученных id (`thread_cache.js:30`, `:61`), а наш индекс упорядочен по тому же `message_id`.

### B.5. Наполнение и поддержка индекса

| Событие | Действие |
|---|---|
| `mail.message.create` | В существующем override (`streams/models/mail_message.py:49-53`) добавить `_streams_index_partners()`: группировка по `model`, чтение зарегистрированных полей одним `read` на модель, батчевый `INSERT ... ON CONFLICT DO NOTHING` (образец SQL — `mail_channel.py:59-75`) |
| `write` по зарегистрированному полю записи-источника | Хук в `mail.thread.write` (уже есть точка — `mail_thread.py:422-429`): если `set(vals) & registered_fields(self._name)` → `DELETE` строк по `(source_model, source_res_id)` + повторный `INSERT` |
| `res.partner.write({'parent_id'/'is_company'})` | `UPDATE streams_message_partner SET commercial_partner_id = … WHERE partner_id IN (…)` — дёшево, `commercial_partner_id` stored+index (`res_partner.py:233-235`) |
| Слияние партнёров | Перестройка строк выжившего партнёра (тот же INSERT…SELECT, что и в backfill) |
| Удаление записи-источника | Ядро удаляет её `mail.message` → `ondelete='cascade'` снимает строки |
| Первичное наполнение / «перестроить» | Post-migration + серверное действие: по одному `INSERT ... SELECT ... FROM mail_message m JOIN <table> r ON r.id = m.res_id JOIN res_partner p ON p.id = r.<field> WHERE m.model = '<model>'` на каждую запись реестра, `ON CONFLICT DO NOTHING` |

Реестр — модель `streams.partner.source` (`model_id`, `field_id`, `active`), сид в `data/`, плюс хук `_streams_partner_ids()` на `mail.thread` для моделей с хопом (`cmr`, `supply.doc`, `supply.settlement` → `shipment_id.company_partner_id`); при наличии override индексатор берёт результат хука вместо реестра.

### B.6. Переключатель охвата

- Поле `streams_partner_scope` (selection `direct`/`related`/`company`) на `res.users.settings` — ядро само отдаёт все неавтоматические поля этой модели в `init_messaging` (образец — `streams/models/res_users_settings.py`).
- Клиент: `registerFieldPatchModel('mail.chatter')` + три кнопки в `t-inherit="mail.ChatterTopbar"` (образец — `streams/static/src/models/chatter.js`, `xml/chatter_topbar.xml`). Смена значения → RPC на сохранение + `thread.cache.update({isLoaded:false})` / `thread.refresh()`.
- Показывать переключатель только когда `thread.model === 'res.partner'`.

---

## C. Ответы на поставленные вопросы (сводно)

**1. Связанные записи** — вариант (б)+(в): реестр «модель → поле» в данных + хук-метод для хопов. Автоскан (а) отвергнут: ~95–100 m2o-полей на ~55 mail.thread-моделях, из них значительная доля означает не контрагента (наша компания, лаборатория, таможенный пост, водитель) или дублирует уже учтённое поле related-зеркалом. Оценка объёма ленты по коду невозможна, но при архитектуре B.1 она и не нужна: стоимость страницы O(limit) при любом размере партнёра.

**2. Компания** — `commercial_partner_id` (`res_partner.py:233-235`, store+index, рекурсивно поднимается до верхней компании через `_compute_commercial_partner`, `:340-346`). Обход `child_ids` вручную не нужен и вреден: `child_ids` ограничен активными и только прямыми детьми (`res_partner.py:166`), а `commercial_partner_id` покрывает произвольную глубину и уже хранится в БД. Прецедент такого же выбора в репозитории — `velesagro_crm/models/connect_messagebox_message.py:83`.

**3. Механика ленты** — override роута `/mail/thread/messages` (не `_message_fetch`), материализованный индекс вместо OR-домена, не-sudo `search` для ACL, over-fetch ×4 из-за `mail_message.py:279-281` + `thread_cache.js:247-249`. Существующие индексы `mail_message`: `model`, `res_id`, композит `(model, res_id)` (`mail_message.py:103,104,249-252`) — для нашей задачи их недостаточно, нужны свои.

**4. UI** — ссылку «on SO0025» ничего делать не нужно: она ядровая (`message.xml:111-119`), кликабельная (`thread.js:1892-1898`) и появляется автоматически, если `originThread` не подменён. Наш патч `_computeThreads` (`streams/static/src/models/message.js:67-76`) расширяется на виртуальный тред. Существующий скрыватель ссылки в `xml/message.xml` не мешает (условие на `streamsChannelKind === 'record'`). `thread_cache._computeFetchedMessages` (`thread_cache.js:79-90`) виртуальные сообщения не выкинет, потому что они попадут в `thread.messages`. Что ломается: иконки статуса доставки у виртуальных сообщений не рисуются (`message.xml:84` требует `originThread === threadView.thread`) — считаю приемлемым.

**5. Взаимодействие со streams** — партнёрский канал остаётся реальным без единой правки: `_streams_link_existing_channels` линкует только по своей паре (model,res_id) (`mail_message.py:120-160`), `_streams_attach_history` тянет историю SQL-ом по `model = res_model AND res_id = res_id` (`mail_channel.py:87-105`), `_streams_message_domain` (`mail_channel.py:245-250`) виртуальную ленту не видит. **Инвариант, который надо закрепить тестом:** сообщение лида/заказа никогда не появляется в `stream_channel_ids` канала партнёра. Виртуальные `change` — предлагаю **не показывать** (шум: «Stage: New → Qualified» на 500 заказах); `change` по самому партнёру показываются как сейчас, по фильтру §6.

**6. Запись из чаттера партнёра** — спец-кода не требуется. Композер берёт `model`/`id` из `mail.chatter.thread` (`chatter.js:230-274`), а не из сообщения; поскольку `originThread` мы не подменяем, тем более ничего не ломается. Сообщение постится на `res.partner`, проходит штатный конвейер streams (`mail_thread.py:150-186`): классификация, ленивое создание/реанимация канала партнёра, `_streams_broadcast`. Единственное — индексатор B.5 должен проиндексировать его под самим партнёром, чтобы оно не выпало из агрегированной ленты.

**7. Производительность** — рекомендация: **materialized**. Обоснование: on-the-fly требует на каждую страницу (а) сбора `res_id` по ~15 моделям, (б) OR-домена из тысяч пар, (в) сортировки `id DESC` без подходящего индекса — единицы секунд на скролл у крупной компании, и деградация линейна по её размеру. Materialized даёт index-only scan O(30) при любом размере, ценой одной строки на связь сообщения с партнёром и обработки трёх событий (`create` сообщения, `write` партнёрского поля, `write` `parent_id` партнёра). Затраты на запись — один батчевый `INSERT ... ON CONFLICT` в существующем override `mail.message.create`, что сопоставимо с уже работающим `_streams_link_existing_channels`. Риск объёма m2m-связей из §17.1 роадмапа здесь тот же самый и решается так же — батчингом.

**8. Конфликт с velesagro_crm** — конфликта нет, и это доказуемо:
- При реализации через роут (B.3) наш код до `_message_fetch` вообще не доходит с «лидовой» формой домена.
- Даже при реализации через `_message_fetch` детектор `_messagebox_chatter_lead` требует, чтобы **все** термы домена были 3-элементными списками (`velesagro_crm/models/mail_message.py:18-20`); любой OR-домен содержит строку `'|'` → детектор возвращает пустой recordset → `super()`. Задвоения не будет ни в каком порядке MRO.
- Раскрутка цепочки: партнёр → лид → messagebox. Виртуальная лента партнёра включит сообщения лида (`model='crm.lead'`), но **не** messagebox-сообщения этого лида — склейка velesagro_crm срабатывает только на чаттере самого лида. Чтобы паритет был, регистрируем `connect_messagebox.message.matched_partner_id` (`velesagro_crm/models/connect_messagebox_message.py:49-65`, computed **store=True**) как источник; дублей не возникает — это разные `mail.message`, а `UNIQUE(message_id, partner_id)` страхует остальное. Присутствие `connect_messagebox.message` в `STREAMS_MODEL_BLACKLIST` (`mail_thread.py:16-21`) индексации не мешает — чёрный список касается только создания каналов.
- **Что из velesagro_crm категорически не копировать:** `self.sudo().search(...)` (`velesagro_crm/models/mail_message.py:78`). В связке с подменой JSON это означает полное отсутствие серверных проверок (`mail_message.py:271-274` + `:377`). Для партнёра это отдало бы любому, кто видит контакт, содержимое всех его заказов, счетов и поставок.

---

## D. Риски

1. **Дрейф индекса.** Любой путь записи в обход ORM (сырой SQL, `_write`, миграции, импорты с `ON CONFLICT`) оставит индекс неполным. Обязателен серверный экшен «Rebuild partner message index» и, возможно, ночной крон сверки счётчиков.
2. **`isAllHistoryLoaded` false-positive.** `thread_cache.js:247-249` в связке с ACL-усадкой страницы (`mail_message.py:279-281`) обрывает историю. Митигируется over-fetch'ем, но при пользователе с очень узкими правами 5 итераций может не хватить — нужен тест на пользователе с `ir.rule`.
3. **Утечка `record_name`.** `_message_format` считает его sudo (`mail_message.py:859-867`). Для сообщений, прошедших ACL, это норма; но если когда-нибудь появится «показывать факт наличия недоступных сообщений» — имя записи утечёт. Не делать.
4. **Сообщение-синглтон в клиентском сторе.** Даже без подмены `model/res_id` наш `_computeThreads` навсегда привязывает сообщение к треду партнёра на время сессии. Практически безвредно (`thread.messages` — множество), но при одновременно открытых чаттере партнёра и Discuss-канале заказа стоит проверить `_shouldMessageBeSquashed` (`thread_view.js:318-339`) — соседние сообщения из разных документов не должны склеиваться.
5. **`mark all as read`.** `thread_cache.js:278-302` строит домен по `[model, res_id]` треда, то есть виртуальные needaction не гасятся. Скорее фича, чем баг, но пользователи будут спрашивать.
6. **Стоимость `_search` на странице.** `_find_allowed_model_wise` (`mail_message.py:326-330`) делает по одному `search` на каждую модель в странице — при пёстрой ленте это 10–15 дополнительных запросов на скролл, каждый со своими `ir.rule`. Замерить на реальном партнёре.
7. **`change`-шум при массовых операциях.** Даже отфильтрованные на выдаче, они попадут в индекс и раздуют таблицу (импорт по тысячам записей). Возможно, `change` для чужих моделей не индексировать вовсе.
8. **Реестр как источник ошибок.** Ошибочно включённое поле (`supply.shipment.recipient` = наша компания) немедленно засоряет ленту всех партнёров. Нужны валидация при добавлении (предупреждение, если поле related или указывает на компанию из `res.company.partner_id`) и «предпросмотр: сколько сообщений добавит эта запись реестра».

---

## E. Открытые вопросы архитектору

1. **Дефолт охвата.** `related` или `company`? Для контакта внутри организации `company` — это, вероятно, ожидаемое поведение («что вообще происходит с этим клиентом»), но при первом открытии оно может удивить. Персонально per-user или per-partner-type?
2. **Виртуальные `change`** — совсем не показывать, или показывать как шестой переключатель фильтра (выкл по умолчанию)? Первое дешевле и однозначно; второе последовательнее по отношению к §6.
3. **Второстепенные поля** (`partner_invoice_id`, `partner_shipping_id`, `transport.order.delivery`, `forwarder_contact`) — включать в реестр по умолчанию или оставить админу? Включение расширяет ленту в разы для логистических партнёров.
4. **`coa.order.lab`, `transport.order.checkpoint/customs_clearance`, `email.document.to_forwarder`** — это «контрагент» в смысле чаттера или служебная сторона? Ответ определяет, увидит ли лаборатория/таможенный агент свою историю в собственной карточке.
5. **Уровень Company для контакта-физлица без родителя** — прятать переключатель или показывать неактивным?
6. **Права на переключатель.** Ограничивать ли уровень Company группой (менеджеры), чтобы рядовой сотрудник не собирал одним кликом сводку по всей организации? Технически ACL не нарушается (каждое сообщение проверяется), но агрегация сама по себе информативна.
7. **Отметка прочитанным** виртуальных needaction из чаттера партнёра — оставить как есть (не гасить) или расширить домен `_onChangeMarkAllAsRead`?
8. **Порядок фаз.** Это фаза 4 роадмапа или вставка перед фазой 2 (Changes)? Индексатор трогает `mail.message.create` — ту же точку, что и будущая механика подписок на поля; делать оба изменения в одном заходе может быть дешевле.
---

## Решения по развилкам (2026-08-18, архитектор + пользователь)

1. **Хранилище — SQL VIEW, не материализованная таблица** (решение пользователя).
   Обычная (не materialized) вьюха `streams_partner_message`, генерируемая из
   реестра «модель → поле» как UNION ALL веток
   `SELECT m.id AS message_id, r.<field> AS partner_id, p.commercial_partner_id
      FROM mail_message m JOIN <table> r ON m.model='<model>' AND m.res_id=r.id
      JOIN res_partner p ON p.id = r.<field>`.
   Пересоздаётся при изменении реестра (init()/write реестра). Плюсы: нет дрейфа,
   нет триггеров на create/write, нет rebuild-крона. Минус — стоимость страницы
   зависит от размера партнёра (сортировка после bitmap-скана веток). Прецедент
   SQL-view в проекте есть (partner_moves_report; помнить про GRANT для
   пользователя БД среды!). ПЛАН: реализуем view, меряем на прод-копии на самом
   крупном партнёре; если страница > ~300 мс — эскалация к материализованной
   таблице из раздела B.1 (интерфейс _page() оставить абстрактным, чтобы замена
   была локальной).
2. Дефолт охвата — `related`; переключатель per-user (res.users.settings).
3. Виртуальные `change` — не показывать (место изменений — чаттер/канал своей
   записи и личный Changes).
4. Второстепенные поля (partner_invoice_id, partner_shipping_id,
   forwarder_contact и т.п.) в реестр по умолчанию НЕ включаются — админ
   добавляет через UI реестра при необходимости. Служебные стороны (lab,
   checkpoint, customs, наша компания) — не включаются.
5. Company-переключатель для физлица без родителя — скрывать.
6. Ограничения группой на уровень Company не вводим (ACL честно проверяется
   по-записно).
7. mark-all-read виртуальных needaction — не расширяем (гасятся на записи).
8. Очередность: отдельная фаза ПОСЛЕ фаз 3-5 исходного ТЗ (нумерация — Фаза 6),
   если пользователь не попросит раньше.
