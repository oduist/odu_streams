# streams — Дизайн Фазы 1b (клиент: Discuss и чаттер)

Продолжение `design-phase1.md` (Фаза 1a, серверное ядро — сделана: подтипы,
каналы записей, m2m `stream_channel_ids`, sync followers↔участники, форк
unread, контроллер `/mail/channel/messages`). Здесь — клиентская часть на
Odoo 15 OWL/messaging-моделях + несколько серверных доводок.

Все ссылки file:line на ядро — ~/Dev/odoo_15. Фронтенд 15-й: messaging-модели
в `addons/mail/static/src/models/*/*.js` (патчи через
`registerClassPatchModel` / `registerFieldPatchModel` /
`registerInstancePatchModel` / `registerIdentifyingFieldsPatch` из
`mail/static/src/model/model_core.js`), компоненты OWL в
`components/*`, компоненты патчатся `patch(Component.prototype, ...)` из
`web.utils`. Повторный `registerMessagingComponent` с тем же именем бросает
исключение. Ассеты объявляются в manifest `assets` (web.assets_backend,
web.assets_qweb).

## Решения пользователя

- Автор первого сообщения остаётся участником канала (ядровое поведение
  mail.channel.create не вырезаем).
- Кнопки Send Email из velesagro_crm/email_document пока НЕ удаляем: они
  сосуществуют с нашими; унификация — отдельным шагом после 1b.
- В ai_chat переименовать «stream» → «ai_chat_stream» (bus-тип
  `ai_chat.stream/update` в ai_chat_session.py:1074 и js/permission_message.js,
  CSS `o_AiChatStream_*`). Сделать в этой фазе, бамп версии ai_chat.

## Состав Фазы 1b

### 1. Проекции в клиенте (критическая точка)

Проблема: клиент строит принадлежность сообщения тредам ТОЛЬКО из
`originThread` = (model, res_id): `models/message/message.js:84-99`
(convertData), `:604-619` (`_computeThreads` — единственный источник
`message.threads`; `Thread.messages` — readonly-инверсия). Кэш треда активно
вычищает лишнее: `models/thread_cache/thread_cache.js:79-90`
`_computeFetchedMessages` unlink-ает всё, чего нет в `thread.messages`. Без
патча вся серверная выдача и bus невидимы.

Патчи (static/src/models/message/message.js):
- `registerClassPatchModel('mail.message', ...)`: `convertData` читает из
  payload `stream_channel_ids` (список id) и `streams_kind` (строка/false) —
  сервер уже кладёт оба в `_message_format` (фаза 1a).
- Поля через `registerFieldPatchModel`: `streamsKind` (attr),
  `streamChannelIds` (attr, список id).
- `registerInstancePatchModel('mail.message')._computeThreads()`: взять
  результат `this._super()`, добавить
  `messaging.models['mail.thread'].insert({model: 'mail.channel', id})` для
  каждого id из `streamChannelIds`.
- `_computeIsHighlighted` (`message.js:504-510`) — упоминание подсвечивается и
  в канале-проекции.
- `_shouldMessageBeSquashed` (`models/thread_view/thread_view.js:318-339`) —
  не расклеивать соседние проекции («different document thread»).
- Шаблон `components/message/message.xml:111-119` (блок originThread «on
  <document>»): в канале записи, чей res_model/res_id совпадает с origin
  сообщения, ссылку «on …» не показывать (t-inherit extension).
- `_onChangeMarkAllAsRead` (`thread_cache.js:278-303`): домен для канала
  расширить проекциями (`['|', '&', ('model','=','mail.channel'),
  ('res_id','=',id), ('stream_channel_ids','in',[id])]`).

Каналу нужен `channel_kind` и (res_model, res_id) на клиенте:
- Python: `channel_info()` (mail.channel) — добавить `channel_kind`,
  `res_model`, `res_id`.
- JS: `registerFieldPatchModel('mail.thread')` — `streamsChannelKind`,
  `streamsResModel`, `streamsResId`; `registerClassPatchModel('mail.thread')`
  `convertData` — прочитать их из channel_info payload.

### 2. Категория сайдбара «Messages» (§11.3)

Каналы записей — внизу сайдбара, отдельной группой. `channel_type` остаётся
'channel' (не изобретать новый тип: все computeds
`discuss_sidebar_category_item.js` — switch по channelType и на неизвестном
типе дают undefined). Маршрутизация в категорию — по `streamsChannelKind`.

Образец из 4-5 файлов — im_livechat (клон структуры):
1. `im_livechat/static/src/models/discuss/discuss.js:19-27` —
   `registerFieldPatchModel('mail.discuss', {categoryStreams: one2one(...)})`.
2. `.../discuss_sidebar_category/discuss_sidebar_category.js:6-15` — обратное
   поле + `registerIdentifyingFieldsPatch`.
3. `.../messaging_initializer/messaging_initializer.js:6-23` —
   `_initResUsersSettings` с `insertAndReplace({...})`; требует boolean-поля
   на res.users.settings: добавить в Python
   `is_discuss_sidebar_category_streams_open` (Boolean, default True) — поля
   res.users.settings попадают в init_messaging автоматически
   (`res_users_settings._res_users_settings_format`).
4. `.../thread/thread.js` — патч `_getDiscussSidebarCategory`
   (ядро: `thread.js:1915-1923`, switch по channel_type): если
   `streamsChannelKind === 'record'` → categoryStreams, иначе super.
5. XML `t-inherit="mail.DiscussSidebar"` — вставить категорию внизу.

Быстрый фильтр (§11.3): ядровый input `sidebarQuickSearchValue`
(`discuss.js:437-439`, обработчик `onInputQuickSearch` `discuss.js:244-251`,
фильтрация `discuss_sidebar_category.js:93-104` `_computeFilteredCategoryItems`)
показывается только при >19 запиненных каналов
(`components/discuss_sidebar/discuss_sidebar.xml:18-20`) — переопределить
условие шаблона, чтобы поле было видно всегда. Фильтрация нашей категории
получается бесплатно.

Режим «имя + содержимое» (§11.3 опция) — НЕ в этой фазе (фаза 5, требует
pg_trgm).

### 3. Фильтры потоков канала (§6)

Пять клиентских фильтров отображения в канале записи: Comments, Notes,
Customers (message), Changes (по умолчанию ВЫКЛ), Activities. Это настройка
рендера, не подписка: лента канала грузится целиком, скрытие — на клиенте по
`message.streamsKind` (сообщения «прочее» — streams_kind=false — показывать
всегда).

Персистентность per-channel per-user: JSON-поле `streams_filters` (Char) на
`mail.channel.partner` + RPC-метод на mail.channel
(`streams_set_filters(channel_id, filters)`); в `channel_info()` отдавать
текущие фильтры члена (`_channel_info_format_member` или прямо в info).
Дефолт: {'comment': True, 'note': True, 'message': True, 'change': False,
'activity': True}.

UI: панель-тумблеры в шапке треда (`components/thread_view_topbar` в 15 нет —
шапка Discuss это `components/discuss/discuss.xml` + ThreadViewTopbar есть?
проверить: в 15 шапка канала — `mail/static/src/components/thread_view_topbar`
существует с 15.0; если нет — кнопки в `discuss.xml` рядом с контролами
канала). Показывать только для каналов с `streamsChannelKind === 'record'`.
Фильтрация: патч `thread_view.js` — computed списка отображаемых сообщений
(`threadView.messages` → фильтр по включённым потокам).

### 4. Кнопки чаттера (§11.1, без Notify и Changes — это фазы 3 и 2)

Чаттер 15 — OWL: компонент `components/chatter_topbar/chatter_topbar.xml`
(Send message :9-21, Log note :22-34), обработчики в модели
`models/chatter/chatter.js` (`onClickSendMessage:140-146`,
`onClickLogNote:95-101`, биндинг в `_created:34-42`).

Целевая раскладка 1b:
- **Comment** — первая кнопка (заменяет ядровую Send message): открывает
  композер в режиме comment → постит `mail.mt_comment`, message_type
  'comment', БЕЗ получателей-партнёров (внутренний комментарий; писем нет —
  сервер фазы 1a это гарантирует). Фактически это ядровый режим
  «Send message» с `isLog=false`; следить, чтобы контракт `isLog`
  сохранился — на нём построен `mail_extra_recipients`
  (`composer_view.js: _getMessageData` добавляет extra_email_to при !isLog).
- **Note** — ядровая Log note (переименовать label в Note).
- **Send Message** — внешняя переписка: открывает полный композер
  (`openFullComposer` — `models/composer_view/composer_view.js:230-263`,
  action `mail.compose.message`) с контекстом
  `default_subtype_xmlid='streams.mt_message'` (проверить, что
  mail.compose.message уважает default_subtype_xmlid; если нет — передать
  `custom context` и переопределить `mail.compose.message._prepare_mail_values`
  либо `get_mail_values`, чтобы подтип стал streams.mt_message). Существующие
  кнопки Send Email от velesagro_crm/email_document не трогать.
- **Schedule Activity** — как есть.

Шаблон — `t-inherit="mail.ChatterTopbar"` extension (xpath по
`o_ChatterTopbar_buttonSendMessage` / `buttonLogNote`), новые обработчики —
`registerInstancePatchModel('mail.chatter')` + патч `_created` для bind.

Правка ядровой отправки в канале записи: композер канала
(`composer_view.js:291-302`) для mail.channel всегда шлёт `mail.mt_comment` —
для канала записи это правильно (comment по умолчанию, §11.2), «Note из
канала» и «Send Message из канала» — вне 1b (потребует режимов композера
канала; отметить как TODO фазы 1c/2).

ВАЖНО: сообщение, отправленное из канала записи (модель mail.channel), по ТЗ
должно попасть и в чаттер записи. Это обратная проекция: message_post на
mail.channel с channel_kind='record' → серверный override в streams:
перепривязать сообщение к записи (model=res_model, res_id=res_id) и связать с
каналом через m2m (тогда обе проекции работают, unread/чаттер согласованы).
Реализовать на сервере: mail.channel.message_post → если channel_kind='record'
и подтип comment/note — постить НА ЗАПИСЬ (record.message_post) вместо канала
и вернуть сообщение (лента канала покажет его через проекцию, bus — через
_streams_broadcast). Тест обязателен.

### 5. Серверные доводки

- `channel_info()` — новые ключи (см. §1) + фильтры участника (см. §3).
- Подавить шумовые сообщения «invited/joined» ядра в каналах записей:
  mail.channel.add_members постит notification в канал — для
  channel_kind='record' пропускать этот message_post (контекстный флаг вокруг
  super в нашем override add_members).
- Батч ACL при broadcast: `_streams_partner_can_read` зовётся на каждого
  участника; заменить на один проход — собрать внутренних пользователей
  участников, для каждого пользователя один `_filter_access_rules_python`
  без per-partner повторов (или сгруппировать пользователей по группам прав).
  Цель: O(участники) лёгких проверок, максимум несколько SQL на сообщение.
- bus_actions НЕ дублировать: для UI-команд использовать существующий сервис
  (`addons_veles/bus_actions`), свои bus-типы — только для messaging-надобностей
  (`mail.channel/new_message` уже используется).

### 6. Тесты

Python (tests/test_streams_ui.py или дополнение test_streams.py):
- message_post в канал записи (channel_kind='record') → сообщение лежит на
  записи (model=res_model), связано с каналом, в чаттере записи видно.
- add_members на record-канале не постит «invited»-сообщение.
- channel_info содержит channel_kind/res_model/res_id/фильтры.
- streams_set_filters сохраняет и отдаёт фильтры per-user.
- Батч-ACL broadcast: участник без прав не получает уведомление (переписать
  существующую проверку под новый код).

Браузерный прогон (обязателен, инструменты mcp__browser-rendering__*;
подгрузить схемы ОДНИМ ToolSearch: new_page, navigate_page, evaluate_script,
fill_form, click, type_text, take_screenshot, close_page):
1. Логин admin в среде.
2. На карточке партнёра написать Comment → перейти в Discuss → канал в группе
   Messages, сообщение видно.
3. Написать в канал → сообщение появилось в чаттере записи.
4. Переключить фильтр Changes → change-сообщения появились/скрылись.
5. Быстрый фильтр сайдбара сужает список.
Правила экономии вызовов: не делать take_snapshot, ходить по стабильным
o_-селекторам, скриншоты сохранять в корень воркспейса (не /tmp), итог
подтверждать одним скриншотом или одним run_odoo_shell.

### Вне 1b
Notify и Changes кнопки (фазы 3 и 2), собственная полная форма Send Message
(пока используем ядровой полный композер с подтипом message; своя форма — при
унификации с velesagro_crm/email_document), Note/Send Message из композера
канала, поиск по содержимому, переработка сайдбара сверх категории Messages.
