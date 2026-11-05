# Фаза 8 — исследование: карта легаси-клиента 15 и сверка с портом 19

Исследовательский документ подготовки фазы 8 (веб-UI на OWL 2 + Store).
Разбирает `static/legacy15/` (30 файлов, ~3.3k строк, messaging-фреймворк
Odoo 15) и сверяет каждую фичу с уже портированным серверным кодом
`addons/streams/{models,controllers,wizard}` на Odoo 19.

Источники требований: `docs/roadmap.md` §6, §8.3, §11, §12 и разделы
«Сделано → Фаза 1/2/3». Компактный референс семантики — мобильный клиент
(`addons/streams_mobile/controllers/api.py`, контракт
`streams_mobile/docs/api-v1.md`, Flutter `app/lib/`).

Все ссылки вида `файл:строка` — на состояние репозитория на момент
коммита `218e058`.

---

## (а) Карта файлов легаси

### `models/` — патчи messaging-моделей Odoo 15

| Файл | Строк | Что делает |
|---|---|---|
| `models/thread.js` | 69 | Поля треда `streamsChannelKind` / `streamsFilters` / `streamsResModel` / `streamsResId`; `convertData` разбирает `channel_kind`, `res_model`, `res_id`, `streams_filters`; `_getDiscussSidebarCategory` маршрутизирует record-каналы в категорию «Messages» (личные Changes/Notifications оставлены в ядровой Channels). |
| `models/message.js` | 77 | Поля `streamsKind` / `streamChannels`; `convertData` разбирает `streams_kind` и `stream_channel_ids`; `_computeThreads` добавляет каналы-проекции (без этого лента канала на клиент не доезжает); `_computeIsHighlighted` подсвечивает @mention в канале-проекции. |
| `models/thread_cache.js` | 58 | `_computeOrderedNonEmptyMessages` — клиентская фильтрация ленты по `streamsFilters` (сообщения без `streamsKind` — «прочее» — видны всегда); `_onChangeMarkAllAsRead` — форк домена «прочитать всё» с учётом `stream_channel_ids`. |
| `models/thread_view_topbar.js` | 90 | Шапка канала записи: тумблеры пяти фильтров (`streamsFilterItems`, ярлыки Comments/Notes/Customers/Changes/Activities), `onClickStreamsFilter` (оптимистичный апдейт + RPC `streams_set_filters`, `shadow`), кнопки Notify и Invite customer. |
| `models/chatter.js` | 126 | Кнопки чаттера: `onClickStreamsSendMessage` (ядровый `mail.compose.message` с `default_subtype_xmlid='streams.mt_message'` + `loadNewMessages` на закрытии), `onClickStreamsChanges` (визард `streams.field.subscription.wizard`), `onClickStreamsNotify` (свой композер через мост), `onClickStreamsInvite` (визард `streams.guest.invite.wizard`). |
| `models/discuss.js` | 49 | Поле `categoryStreams`; `_computeHasThreadView` гасит ядровый ThreadView для `changes`/`notifications` (чтобы не вычитывать сообщения впустую); `onInputQuickSearch` раскрывает свёрнутую категорию перед поиском. |
| `models/discuss_sidebar_category.js` | 46 | Регистрация категории «Messages» как identifying-поля; `_computeActiveItem` — активный элемент строит только та категория, в которую канал маршрутизирован (иначе ядровая Channels перетягивает record-канал к себе). |
| `models/discuss_sidebar_category_item.js` | 37 | Для `record` и `changes` счётчик и вклад в счётчик категории берутся из `localMessageUnreadCounter`, а не из needaction. |
| `models/messaging_initializer.js` | 53 | `_init` — передаёт `data.streams_notify` в сервис уведомлений; `_initResUsersSettings` — создаёт категорию «Messages» (`serverStateKey: is_discuss_sidebar_category_streams_open`, `supportedChannelTypes: ['channel']`, сортировка `last_action`) и пробрасывает `is_streams_notify_sound_muted`. |
| `models/messaging_notification_handler.js` | 24 | Перехват bus-типа `streams.changes/updated` → ретрансляция в `messagingBus` событием `streams-changes-updated`. |

### `js/` — сервисы и утилиты

| Файл | Строк | Что делает |
|---|---|---|
| `js/notify_service.js` | 432 | Ядро подсистемы Notify: состояние (`counter`, `channelId`, `defaultTimeout`, `popups`, `stickyIndex`, `isSoundMuted`, `settingsId`), стек попапов и таймеры, пауза/резюм по наведению, батч `streams_notify_popup_shown` (дебаунс 500 мс), звук (`soundEffects.newMessage` только в мастер-вкладке, фолбэк `Audio('/mail/static/src/audio/dm_02')`), Mute через `set_res_users_settings`, подписка на шину (`bus_actions_<uid>`), `markRead`, `openComposer`, `reply`, `openChannel` (+ ленивая вставка канала в messaging), `openRecord`, регистрация `StreamsNotifyContainer` в `main_components`. |
| `js/notify_bridge.js` | 30 | Модульный синглтон-мост messaging ⇄ wowl-сервис с очередью отложенных вызовов (порядок старта не гарантирован). |
| `js/notify_systray.js` | 46 | Колокол в навбаре, `sequence: 50.5` (вплотную слева от Discuss), бейдж `99+`, клик → `openChannel()`. Дропдауна нет намеренно. |
| `js/streams_filters.js` | 27 | Константы `STREAMS_FILTER_DEFAULTS` (change=false, остальные true) и `STREAMS_FILTER_ORDER` (comment, note, message, change, activity) — дубль серверных дефолтов, нужен до приезда `channel_info`. |
| `js/voice_recorder.js` | 138 | Свой рекордер на `MediaRecorder`: выбор mime из `audio/webm;codecs=opus` → `audio/ogg;codecs=opus` → `audio/mp4`, тик раз в секунду, жёсткий стоп на 300 с, обязательный `track.stop()` в `release()`, `buildFileName()` → `voice-YYYYMMDD-HHmmss.{webm,ogg,m4a}`. |

### `components/` — OWL 1 компоненты

| Файл | Строк | Что делает |
|---|---|---|
| `streams_changes_feed/streams_changes_feed.js` | 274 | Лента личного канала Changes: RPC `streams_changes_feed(limit=30)`, рендер «поле: было → стало», клик по имени записи → `do-action` на форму, прочитанность через `IntersectionObserver` (threshold 0.99, дебаунс 600 мс) → `/mail/channel/set_last_seen_message`, синхронизация `serverMessageUnreadCounter` из ленты, перезагрузка по `streams-changes-updated`. Пагинацию не использует. |
| `streams_changes_feed/streams_changes_feed.xml` | 54 | Шаблон: состояния loading/empty, элемент = запись (`o-unread`), внутри — изменения с автором, датой и парой old → new. |
| `streams_notify_feed/streams_notify_feed.js` | 315 | Лента канала Notifications: вкладки Received/Sent, RPC `streams_notify_feed(box, limit=30, before_id)`, `Load more`, прочитанность по доскроллу только во вкладке Received (`IntersectionObserver` 0.9, дебаунс 500 мс) → `streams_notify_mark_read`, живая вставка по `NOTIFY-NEW`, патч по `NOTIFY-UPDATE` (в том числе `read_date` конкретного получателя), Mute-тумблер, `New notification`, Reply. |
| `streams_notify_feed/streams_notify_feed.xml` | 117 | Шаблон ленты: шапка с вкладками/New/Mute, карточка (автор, дата, ссылка на запись, тело `t-raw`, `<audio>`, транскрипт или «Transcribing…», вложения), в Sent — список получателей с «Read at …»/«Unread», в Received — кнопка Reply, `Load more`. |
| `streams_notify_composer/streams_notify_composer.js` | 341 | Диалог отправки: поиск получателей (`res.users.name_search`, домен `share=false, active=true, id not in`, лимит 8, дебаунс 300 мс), чипы, тело, вложения через `/mail/attachment/upload` (`is_pending=true`, `thread_model='mail.notify'`, `thread_id=0`), запись голоса, форсирование sticky при голосе, timeout (3..300) только при выключенном sticky, отправка `streams_notify_send` / `streams_notify_reply`, тост об успехе. |
| `streams_notify_composer/streams_notify_composer.xml` | 137 | Шаблоны body/footer диалога, включая заблокированный чекбокс sticky с подсказкой «Voice notifications are always sticky». |
| `streams_notify_popup/streams_notify_popup.js` | 124 | Контейнер попапов: разделение на transient/sticky, текущий sticky по `stickyIndex`, пагинатор, close/reply/openRecord, pause/resume по mouseenter/mouseleave. |
| `streams_notify_popup/streams_notify_popup.xml` | 87 | Шаблон карточки попапа (автор, время, крестик, ссылка на запись, тело, плеер, транскрипт, вложения, Reply) и контейнера со стеком sticky и пагинатором «N / M». |

### `xml/` — наследования ядровых шаблонов

| Файл | Строк | Что делает |
|---|---|---|
| `xml/chatter_topbar.xml` | 104 | Замена ядровых кнопок: Send message → **Comment**, Log note → **Note** (классы ядра сохранены — на них опираются `velesagro_crm`/`email_document`); добавлены **Send Message**, **Notify**, **Changes**, **Invite customer** с `data-hotkey` и тултипами. |
| `xml/thread_view_topbar.xml` | 38 | В шапке канала записи: **Notify**, **Invite customer** и блок тумблеров фильтров (активный — `btn-primary o-active`). |
| `xml/discuss.xml` | 31 | Подстановка `StreamsChangesFeed` и `StreamsNotifyFeed` вместо ThreadView по `streamsChannelKind`. |
| `xml/discuss_sidebar.xml` | 25 | Быстрый фильтр показан всегда (ядро — с 20-го запиненного канала); категория «Messages» после Chat. |
| `xml/message.xml` | 14 | В канале записи прячется ссылка «on \<документ\>» (канал и есть этот документ); в Inbox/Starred остаётся. |
| `xml/notify_systray.xml` | 16 | Шаблон колокола с бейджем. |
| `scss/streams.scss` | 296 | Стили: тумблеры фильтров, лента Changes, лента Notify, попапы, композер, systray. |

---

## (б) Чек-лист фич UI и их серверные зависимости

Легенда статуса:
- ✅ — API есть в порте 19, контракт совместим;
- ✳️ — API есть, но контракт/имя изменились (клиент 19 пишется под новое);
- ❌ — **разрыв (gap)**: серверной опоры нет, см. раздел (д).

### A. Каналы, лента, сайдбар

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| A1 | Сообщения-проекции попадают в ленту канала записи (m2m «сообщение → канал») | `models/message.js` (`_computeThreads`, `convertData`) | Store-ключ `stream_channel_ids` на сообщении | ✅ `models/mail_message.py:331` (`_to_store_defaults`), поле `:46` |
| A2 | Серверная лента канала возвращает и собственные сообщения, и проекции | — (следствие A1) | форк `mail.message._message_fetch` | ✅ `models/mail_message.py:306`; домен — `models/discuss_channel.py` `_streams_message_domain` |
| A3 | Поток сообщения (`comment/note/message/change/activity`) на клиенте | `models/message.js` | Store-ключ `streams_kind` | ✅ `models/mail_message.py:338`, классификатор `:132` |
| A4 | Фильтрация ленты по потокам на рендере (данные грузятся целиком) | `models/thread_cache.js:16-28` | — (чисто клиентская) | ✅ (клиент) |
| A5 | «Прочее» (сообщения без `streams_kind`) показывается всегда | `models/thread_cache.js:26` | классификатор возвращает пустой kind | ✅ `models/mail_message.py:102` |
| A6 | Тумблеры фильтров в шапке канала, дефолт Changes=выкл | `models/thread_view_topbar.js:61-70`, `js/streams_filters.js`, `xml/thread_view_topbar.xml` | Store-ключ `streams_filters`, дефолты `STREAMS_FILTER_DEFAULTS` | ✅ `models/discuss_channel.py:398-409`, дефолты `models/mail_message.py:28` |
| A7 | Персист фильтра per-channel/per-user по клику | `models/thread_view_topbar.js:74-89` | RPC `streams_set_filters(filters)` | ✳️ `models/discuss_channel.py:411` — **модель переименована** `mail.channel` → `discuss.channel`; хранилище — `discuss.channel.member.streams_filters` (JSON), `models/discuss_channel_member.py:28,51` |
| A8 | Скрытие ссылки «on \<документ\>» в канале записи | `xml/message.xml` | Store-ключи `res_model`/`res_id` канала | ✅ `models/discuss_channel.py:400` |
| A9 | Подсветка @mention у сообщения-проекции | `models/message.js:53-58` | — (клиентская, поверх `stream_channel_ids`) | ✅ |
| A10 | «Прочитать всё» в канале записи покрывает проекции | `models/thread_cache.js:36-56` | В 15 — домен на `mail.message.markAllAsRead`; в 19 прочтение канала идёт через member | ✳️ Форк 15 не нужен: `models/discuss_channel_member.py:251` (`_mark_as_read` ищет последнее сообщение и среди проекций) |
| A11 | Счётчик непрочитанного канала записи не растёт от `change` | `models/discuss_sidebar_category_item.js` (берёт `message_unread_counter`) | форк `_compute_message_unread` | ✅ `models/discuss_channel_member.py:107`, ветка record `:186` |
| A12 | Счётчик личного Changes считает записи, а не сообщения | `models/discuss_sidebar_category_item.js`, `components/streams_changes_feed` (`_syncUnreadCounter`) | ветка changes в `_compute_message_unread` | ✅ `models/discuss_channel_member.py:142` (+ `_streams_unread_change_targets:163`) — **в 19 клиентский костыль синхронизации счётчика не нужен** |
| A13 | Счётчик канала Notifications = непрочитанные уведомления | `components/streams_notify_feed` (`_syncUnreadCounter`) | ветка notifications | ✅ `models/discuss_channel_member.py:133`, счётчик `models/mail_notify.py:418` |
| A14 | Категория сайдбара «Messages» для record-каналов | `models/discuss.js`, `models/discuss_sidebar_category.js`, `models/messaging_initializer.js:32-44`, `xml/discuss_sidebar.xml` | поле `res.users.settings.is_discuss_sidebar_category_streams_open` | ✅ поле есть: `models/res_users_settings.py:16`; **клиентская реализация переписывается целиком** (в 19 сайдбар — другой компонент) |
| A15 | Личные Changes/Notifications — в ядровой категории Channels | `models/thread.js:61-67` | Store-ключ `channel_kind` | ✅ `models/discuss_channel.py:400` |
| A16 | Быстрый фильтр сайдбара виден всегда | `xml/discuss_sidebar.xml:9-11` | — | ✅ (клиент) |
| A17 | Быстрый фильтр раскрывает свёрнутую категорию | `models/discuss.js:41-47` | — | ✅ (клиент) |
| A18 | Поиск в сайдбаре по содержимому сообщений (§11.3, опция) | не реализовано в 15 | эндпоинт полнотекстового поиска + настройка режима | ❌ **gap vs ТЗ** (см. G7) |
| A19 | Для `changes`/`notifications` ядровый ThreadView не строится | `models/discuss.js:29-35`, `xml/discuss.xml` | `channel_kind` | ✅ |
| A20 | Активный элемент сайдбара строит только «своя» категория | `models/discuss_sidebar_category.js:35-45` | — | ✅ (клиент) |

### B. Кнопки чаттера (§11.1)

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| B1 | **Comment** — ядровая кнопка быстрого ответа переименована, шлёт `mt_comment` | `xml/chatter_topbar.xml:10-24` | ядро + классификатор | ✅ `models/mail_message.py:102` |
| B2 | **Note** — ядровая кнопка, `mail.mt_note` | `xml/chatter_topbar.xml:25-39` | ядро | ✅ |
| B3 | **Send Message** — полный композер `mail.compose.message` с `default_subtype_xmlid='streams.mt_message'` | `models/chatter.js:94-125`, `xml/chatter_topbar.xml:40-51` | подтип `streams.mt_message`; в 15 был override `mail.compose.message` | ✳️ подтип есть (`data/mail_message_subtype_data.xml:7`); override **удалён** в фазе 5 как покрытый ядром 19 (roadmap «Фаза 5»), живьём на 19 не проверялся |
| B4 | Перезагрузка ленты чаттера после закрытия композера | `models/chatter.js:117-123` | — | ✅ (клиент) |
| B5 | **Notify** из чаттера с автоподстановкой записи | `models/chatter.js:53-62`, `xml/chatter_topbar.xml:57-68` | RPC `mail.notify.streams_notify_send` (`res_model`/`res_id`) | ✅ `models/mail_notify.py:237` |
| B6 | **Changes** — визард подписки на поля | `models/chatter.js:68-88`, `xml/chatter_topbar.xml:73-84` | модель `streams.field.subscription.wizard`, RPC `streams_get_field_subscription` / `streams_set_field_subscription` | ✅ `wizard/streams_field_subscription_wizard.py:16`; RPC — `models/mail_thread.py:194` и `:226` |
| B7 | **Invite customer** из чаттера (работает и на записи без канала) | `models/chatter.js:28-48`, `xml/chatter_topbar.xml:90-101` | модель `streams.guest.invite.wizard`, контекст `default_res_model`/`default_res_id` | ✅ `wizard/streams_guest_invite_wizard.py:17,52-75` |
| B8 | Классы ядровых кнопок сохранены ради xpath сторонних модулей | `xml/chatter_topbar.xml:4-8` | — | ✅ (учесть при переписывании) |

### C. Шапка канала записи (§11.2)

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| C1 | **Notify** из канала (запись берётся из `res_model`/`res_id` канала) | `models/thread_view_topbar.js:46-55`, `xml/thread_view_topbar.xml:7-11` | Store-ключи канала + `streams_notify_send` | ✅ |
| C2 | **Invite customer** из канала (`default_channel_id`) | `models/thread_view_topbar.js:24-41` | визард по каналу | ✅ `wizard/streams_guest_invite_wizard.py:60` |
| C3 | Переключение Comment/Note в композере канала | **не реализовано в 15** (отступление 5 фазы 1) | обратная проекция `discuss.channel.message_post` пропускает kwargs (в т.ч. `subtype_xmlid`) | ❌ **gap UI**, сервер готов: `models/discuss_channel.py` `message_post` |
| C4 | **Send Message** из композера канала | не реализовано | тот же путь, что B3 | ❌ **gap UI** |
| C5 | Создание активности из канала (§11.2) | не реализовано | синтетические activity-сообщения есть (`models/mail_activity.py`) | ❌ **gap UI** |

### D. Лента личного канала Changes (§8.3)

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| D1 | Загрузка ленты «запись → её изменения» | `components/streams_changes_feed/streams_changes_feed.js:131-154` | RPC `streams_changes_feed(limit, before_id)` | ✳️ `models/discuss_channel.py:269` — модель `discuss.channel` вместо `mail.channel`; формат элемента не менялся (`res_model`, `res_id`, `record_name`, `last_message_id`, `unread`, `changes[].values[]`) — `models/discuss_channel.py:340-350` |
| D2 | Фильтрация `tracking_value` по персональной подписке | сервер | `_streams_find_by_targets` + `_streams_accessible_field_names` | ✅ `models/discuss_channel.py:286-330`, `models/mail_field_subscription.py:76,101` |
| D3 | Ретроактивное скрытие записей без доступа (§8.4) | сервер | `_streams_readable_targets` | ✅ `models/discuss_channel.py:~240` |
| D4 | Имя записи кликабельно → форма | `streams_changes_feed.js:106-121` | `record_name` в элементе ленты | ✅ |
| D5 | Прочитанность по доскроллу (IntersectionObserver + дебаунс) | `streams_changes_feed.js:192-266` | HTTP-маршрут `/mail/channel/set_last_seen_message` | ❌ **маршрута 15 в 19 нет**; серверная логика есть — `models/discuss_channel_member.py:251` (`_mark_as_read` учитывает проекции). См. G1 |
| D6 | Счётчик берётся из самой ленты | `streams_changes_feed.js:163-172` | в 19 — серверный `message_unread_counter` | ✳️ костыль не нужен (см. A12) |
| D7 | Живое обновление ленты по шине | `models/messaging_notification_handler.js`, `streams_changes_feed.js:177-183` | bus-тип `streams.changes/updated` (payload `{id: channel_id}`) | ✅ `models/mail_message.py:300` |
| D8 | Дата изменения в TZ пользователя, пустое значение как «—» | `streams_changes_feed.js:82-101` | `date` в ISO-UTC | ✅ |
| D9 | Догрузка при скролле (`before_id`) | **не реализовано в 15** | параметр есть | ❌ **gap UI**, отмечен и в roadmap «To check / to do» |

### E. Сервис уведомлений и попапы (§12.4)

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| E1 | Стартовый payload: счётчик, id канала, `default_timeout`, накопившиеся попапы | `models/messaging_initializer.js:19-26`, `js/notify_service.js:374-385` | `_init_messaging` → глобальное значение Store `streams_notify` | ✳️ `models/res_users.py:35-48` (`store.add_global_values(streams_notify=...)`), payload — `models/mail_notify.py:492-513`. В 15 приезжало полем `data.streams_notify` из `init_messaging`, в 19 — глобальным значением Store |
| E2 | Подписка на шину и разбор трёх типов | `js/notify_service.js:238-279` | `partner._bus_send(...)` | ✳️ канал `bus_actions_<uid>` **исчез** (`bus_actions` удалён в фазе 5); в 19 доставка адресная на канал партнёра — `models/mail_notify.py:527,535,445,453` |
| E3 | Не-sticky попап гаснет по своему `timeout` | `js/notify_service.js:75-108` | `timeout` в payload, зажат сервером в [3, 300] | ✅ `models/mail_notify.py` (`_streams_create`) |
| E4 | Наведение мыши приостанавливает таймер, уход — возобновляет | `js/notify_service.js:134-144`, `streams_notify_popup.js:102-108` | — | ✅ (клиент) |
| E5 | Sticky складываются в стек с пагинатором; показывается самый свежий | `js/notify_service.js:98-101,146-153`, `streams_notify_popup.xml:63-84` | `is_sticky` в payload | ✅ |
| E6 | Отметка «попап показан» батчем с дебаунсом 500 мс | `js/notify_service.js:159-177` | RPC `streams_notify_popup_shown(ids)` | ✅ `models/mail_notify.py:457` |
| E7 | Накопившиеся попапы при следующем логине | `js/notify_service.js:381-383` | `pending` в `_streams_init_messaging` (не старше 7 дней, лимит 20) | ✅ `models/mail_notify.py:492-513` |
| E8 | Звук на все уведомления, только в мастер-вкладке | `js/notify_service.js:183-215` | — (клиент); имя звука в 15 — `soundEffects.newMessage` (`dm_02`) | ✳️ в 19 другой сервис звуков — уточнить при реализации |
| E9 | Персональный Mute с персистом | `js/notify_service.js:217-232`, `models/messaging_initializer.js:46-50` | поле `res.users.settings.is_streams_notify_sound_muted` + ядровый `set_res_users_settings` | ✅ `models/res_users_settings.py:20` |
| E10 | Колокол в навбаре с бейджем, `sequence` слева от Discuss | `js/notify_systray.js`, `xml/notify_systray.xml` | счётчик из E1/E2 | ✅ (клиент; sequence в 19 пересчитать) |
| E11 | Клик по колоколу открывает личный канал, создавая его лениво | `js/notify_service.js:318-355` | RPC `streams_notify_open_channel` | ✳️ **контракт изменён**: `models/mail_notify.py:472` возвращает `{'channel_id': id, 'data': <Store>}` вместо `channel_info()[0]` (отступление 1 фазы 5) |
| E12 | Переход на запись-источник из попапа/ленты | `js/notify_service.js:357-368` | `res_model`/`res_id`/`record_name` в payload | ✅ `models/mail_notify.py:~370` (`_streams_payload`) |
| E13 | Reply из попапа наследует sticky/timeout родителя | `js/notify_service.js:303-310`, `streams_notify_popup.js:86-94` | RPC `streams_notify_reply(parent_id, vals)` с `setdefault` по sticky/timeout | ✅ `models/mail_notify.py:243` |
| E14 | Счётчик обновляется по `streams.notify/counter` и по ответам `mark_read` | `js/notify_service.js:262-265,285-295` | bus `streams.notify/counter`, RPC `streams_notify_mark_read` → `{counter}` | ✅ `models/mail_notify.py:427-455` |
| E15 | Мост messaging ⇄ wowl-сервис | `js/notify_bridge.js` | — | ✳️ в 19 не нужен (единый OWL 2 env) |

### F. Композер уведомления (§12.2, §12.3)

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| F1 | Поиск получателей (только внутренние, активные, дебаунс 300 мс, лимит 8) | `streams_notify_composer.js:110-143` | `res.users.name_search` с доменом `share=false` | ✅ ядро; сервер дополнительно валидирует (`ValidationError` на share) — `models/mail_notify.py` `_streams_check_recipients` |
| F2 | Чипы получателей и их удаление | `streams_notify_composer.js:145-159` | — | ✅ |
| F3 | Ответ адресуется только автору родителя, выбор получателей скрыт | `streams_notify_composer.js:49-56`, `.xml:12-17` | `streams_notify_reply` подставляет `user_ids=[parent.author_id]` | ✅ `models/mail_notify.py:243-254` |
| F4 | Вложения через ядровый upload (pending-паттерн) | `streams_notify_composer.js:207-225` | `/mail/attachment/upload` (`is_pending`, `thread_model='mail.notify'`, `thread_id=0`) + перепривязка на сервере | ✳️ перепривязка есть — `models/mail_notify.py:209-229`; **формат ответа маршрута в 19 нужно перепроверить** (см. G4) |
| F5 | Запись голоса в виджете (только здесь) | `js/voice_recorder.js`, `streams_notify_composer.js:231-281` | валидация mime/размера/длительности на сервере | ✅ `models/mail_notify.py:190-204` (белый список mime + расширения, 25 МБ, 5 мин) |
| F6 | Голос форсирует sticky, чекбокс блокируется с подсказкой | `streams_notify_composer.js:80-82,276`, `.xml:99-113` | сервер форсирует `is_sticky` и на create, и на write | ✅ `models/mail_notify.py` (`_streams_create` / `write`) |
| F7 | Поле timeout видно только при выключенном sticky, границы 3..300 | `.xml:114-121` | зажим на сервере | ✅ |
| F8 | Дефолтный timeout продукта | `streams_notify_composer.js:36-38` | `default_timeout` в `streams_notify` | ✅ `models/mail_notify.py:115,507`; настройка — `models/res_config_settings.py:34` |
| F9 | Отправка `send` / `reply`, блокировка кнопки, тост | `streams_notify_composer.js:287-334` | `streams_notify_send` / `streams_notify_reply` | ✅ `models/mail_notify.py:237,243` |
| F10 | Notify без привязки к записи (из самого канала Notifications) | `streams_notify_feed.js:117-121` | `res_model`/`res_id` необязательны | ✅ |

### G. Лента канала Notifications (§12.5)

| # | Фича | Легаси | Серверное API | Статус в 19 |
|---|---|---|---|---|
| G1 | Вкладки Received / Sent | `streams_notify_feed.js:107-115`, `.xml:6-19` | RPC `streams_notify_feed(box=...)` | ✅ `models/mail_notify.py:334` |
| G2 | Пагинация `Load more` по `before_id` | `streams_notify_feed.js:147-149,155-178` | параметр `before_id` | ✅ `models/mail_notify.py:334-345` |
| G3 | Прочитанность по доскроллу только в Received | `streams_notify_feed.js:244-307` | RPC `streams_notify_mark_read(ids)` | ✅ `models/mail_notify.py:427` |
| G4 | «Read at …» по каждому получателю в Sent | `.xml:82-96` | `with_recipients=True` в payload | ✅ `models/mail_notify.py:~400` |
| G5 | Живая вставка нового уведомления в открытую ленту | `streams_notify_feed.js:200-209` | bus `streams.notify/new` (payload = элемент ленты + `counter`) | ✅ `models/mail_notify.py:517-527` |
| G6 | Точечное обновление карточки (транскрипт, `read_date` получателя) | `streams_notify_feed.js:214-231` | bus `streams.notify/update` | ✅ `models/mail_notify.py:445,529-535` |
| G7 | Плеер голоса, длительность, транскрипт и статус «Transcribing…» | `.xml:62-74` | `voice{id,mimetype,duration}`, `transcript`, `transcript_state` | ✅ `models/mail_notify.py:~355-395` |
| G8 | Вложения ссылками `/web/content/<id>?download=true` | `.xml:75-81` | ACL через `ir.attachment.check` (своих правил нет) | ✅ |
| G9 | Кнопка `New notification` в шапке ленты | `streams_notify_feed.js:117-121` | см. F10 | ✅ |
| G10 | Mute-тумблер в шапке ленты | `streams_notify_feed.js:139-145` | см. E9 | ✅ |

**Итого: 58 гранулярных фич** (A: 20, B: 8, C: 5, D: 9, E: 15, F: 10, G: 10 — минус пересечения по нумерации разделов), из них **7 отмечены как разрывы** (A18, C3, C4, C5, D5, D9 и контрактные ✳️-переходы E1/E2/E11/A7/D1).

---

## (в) Таблица bus-типов

Слева — что слушал легаси-клиент 15, справа — что реально шлёт порт 19
(`grep _bus_send` по `addons/streams`).

| Тип (15, клиент слушал) | Где в легаси | Тип (19, сервер шлёт) | Где в 19 | Payload | Статус |
|---|---|---|---|---|---|
| `streams.notify/new` | `js/notify_service.js:14,248` | `streams.notify/new` | `models/mail_notify.py:54,527` | `_streams_payload(recipient=row)` + `counter`; адресно партнёру получателя | ✅ совпадает |
| `streams.notify/update` | `js/notify_service.js:15,254` | `streams.notify/update` | `models/mail_notify.py:55,445,535` | либо `{id, recipient:{user_id,name,read_date}}`, либо `{id, ...patch}` (транскрипт) | ✅ |
| `streams.notify/counter` | `js/notify_service.js:16,262` | `streams.notify/counter` | `models/mail_notify.py:56,453` | `{counter}` | ✅ |
| `streams.changes/updated` | `models/messaging_notification_handler.js:17` | `streams.changes/updated` | `models/mail_message.py:300` | `{id: <channel_id>}`, только владельцу канала, без тела | ✅ |
| `mail.channel/new_message` (ядро 15; проекции слал сервер) | ядровый обработчик | `discuss.channel/new_message` | `models/mail_thread.py:366` | `{id: channel_id, data: <Store персонально>}` адресно каждому партнёру с правом чтения записи | ✳️ **тип переименован ядром 19** |
| — (в 15 правки гостя шли `mail.channel/insert`/ядровыми) | — | `mail.record/insert` | `models/mail_channel_external_participant.py:691` (`Store(bus_channel=recipient).add(message).bus_send()`) | Store-патч сообщения (правка/удаление/реакция гостя) | ✳️ **новый тип в 19**, клиент 15 его не знал |
| канал шины `bus_actions_<uid>` | `js/notify_service.js:276` | — | удалён вместе с зависимостью `bus_actions` (фаза 5) | — | ❌ **исчез**: в 19 всё едет на канал партнёра, ручная подписка не нужна |

Референс мобильного клиента (`app/lib/state/poll_service.dart:85-101`)
разбирает ровно эти шесть типов; неизвестные молча пропускает. Для
`discuss.channel/new_message` и `mail.record/insert` payload не
разбирается — по событию перезапрашивается лента (упрощение MVP,
для OWL-клиента так делать не нужно: Store-payload прикладной).

---

## (г) Таблица Store-ключей

| Ключ (19, сервер) | Где отдаётся | Носитель | Как назывался/потреблялся в легаси 15 | Статус |
|---|---|---|---|---|
| `channel_kind` | `models/discuss_channel.py:400` | `discuss.channel` | `data.channel_kind` → поле `streamsChannelKind` (`models/thread.js:35-37`) | ✅ потреблялся |
| `res_model` | `models/discuss_channel.py:400` | `discuss.channel` | → `streamsResModel` (`models/thread.js:38-40`) | ✅ |
| `res_id` | `models/discuss_channel.py:400` | `discuss.channel` | → `streamsResId` (`models/thread.js:41-43`) | ✅ |
| `streams_filters` | `models/discuss_channel.py:401-408` (только при `target.is_current_user`) | `discuss.channel` | → `streamsFilters`, мержится поверх `STREAMS_FILTER_DEFAULTS` (`models/thread.js:44-47`) | ✅ |
| `streams_kind` | `models/mail_message.py:338` | `mail.message` | → `streamsKind`, `undefined` для «прочего» (`models/message.js:32-34`) | ✅ |
| `stream_channel_ids` | `models/mail_message.py:334-336` | `mail.message` | → `streamChannels` через `insertAndReplace(id → {id, model:'mail.channel'})` (`models/message.js:35-41`) | ✳️ модель в маппинге теперь `discuss.channel`; ключ отдаётся **плоским списком id**, без типизированной связи Store |
| `streams_notify` (глобальное значение: `counter`, `channel_id`, `default_timeout`, `pending[]`) | `models/res_users.py:46-48` → `models/mail_notify.py:492-513` | глобальные значения Store | `data.streams_notify` из `init_messaging` (`models/messaging_initializer.js:21-24`) | ✳️ канал доставки изменён (`add_global_values`), содержимое то же |
| `is_discuss_sidebar_category_streams_open` | `models/res_users_settings.py:16` (через ядровую сериализацию настроек) | `res.users.settings` | `_initResUsersSettings` → `serverStateKey` категории (`models/messaging_initializer.js:32-44`) | ✅ поле есть; способ доставки в 19 — ядровый Store `res.users.settings` |
| `is_streams_notify_sound_muted` | `models/res_users_settings.py:20` | `res.users.settings` | `service.initSettings({id, is_streams_notify_sound_muted})` | ✅ |

**Чего не хватает в Store 19 для UI:**

1. `message_unread_counter` для личных каналов теперь считается сервером
   (`models/discuss_channel_member.py:133,142`) — клиенту **не нужно**
   синхронизировать счётчик из ленты, как это делали
   `streams_changes_feed._syncUnreadCounter` и
   `streams_notify_feed._syncUnreadCounter`. Проверить, что значение
   реально доезжает до Store у канала без открытого ThreadView.
2. `stream_channel_ids` — сырые id. Для OWL 2 удобнее `Store.Many('discuss.channel')`,
   иначе клиент вручную резолвит id → запись Store (мелкая, но
   тиражируемая работа в каждом компоненте).
3. Нет Store-ключа «канал доступен только на чтение / я не участник» —
   в 15 это выводилось из `members`; проверить при переписывании композера.

---

## (д) Разрывы (gaps) — чего порту 19 не хватает для UI

### G1. Нет маршрута «отметить прочитанным» для лент Changes/Notifications ❗

Легаси-лента Changes звала HTTP-маршрут 15
`/mail/channel/set_last_seen_message`
(`components/streams_changes_feed/streams_changes_feed.js:253-259`).
В 19 этого маршрута нет; серверная логика с учётом проекций есть —
`models/discuss_channel_member.py:251` (`_mark_as_read`), но публичной
точки входа модуль не добавляет.

Мобильный клиент решил это своим эндпоинтом:
`addons/streams_mobile/controllers/api.py:333-351` — находит `member` по
`(channel_id, partner_id)` и зовёт `member._mark_as_read(last_message_id)`,
возвращая `{'ok': True, 'unread': ...}`.

Для веба: либо использовать ядровый маршрут 19 (нужно подтвердить его имя
и сигнатуру в ядре — `discuss.channel.member` метод/route), либо добавить
свой RPC по образцу мобильного. **Решение нужно принять в дизайне фазы 8.**

### G2. `streams_notify_open_channel` вернул другой контракт ❗

`models/mail_notify.py:472-490` отдаёт `{'channel_id': id, 'data': <Store результат>}`
вместо `channel_info()[0]` из 15 (зафиксировано как отступление 1 фазы 5).
Легаси-код `js/notify_service.js:318-355` строил канал через
`Thread.convertData(info)` + `pin()` — этот путь мёртв.

Открытый вопрос: достаточно ли `Store().add(channel).get_result()` для
того, чтобы канал появился в сайдбаре у пользователя, у которого он
создан **после** загрузки страницы (в `data` может не быть self-member,
`is_pinned` и т.п.). Проверить при реализации; при недостаче — расширить
payload на сервере.

### G3. Bus-канал `bus_actions_<uid>` исчез ❗

`js/notify_service.js:269-279` вручную подписывался на
`bus_actions_<session.uid>` и звал `startPolling()`. В 19 зависимость
`bus_actions` удалена, доставка идёт `partner._bus_send(...)` на канал
партнёра. Клиент 19 должен вешать обработчик на ядровый bus-сервис без
собственной подписки; longpolling в 19 отсутствует как таковой (в
мобильном заменён на `/v1/poll`, `api.py:517`).

### G4. Формат ответа `/mail/attachment/upload` в 19 не зафиксирован ❗

Композер уведомления (`streams_notify_composer.js:207-225`) читал плоский
`{id, name}` и полагался на pending-паттерн
(`is_pending=true`, `thread_model='mail.notify'`, `thread_id=0`).
Серверная перепривязка в 19 есть и рассчитывает ровно на этот путь
(`models/mail_notify.py:209-229`: `res_model='mail.compose.message'`,
`res_id=0`, `create_uid == env.uid`), но **ответ ядрового маршрута в 19
Store-образный**, и старый разбор `result.id` может не работать.
Проверить перед реализацией; мобильный обошёл маршрут собственным
`/v1/attachment/upload` (`api.py:558`).

### G5. Send Message: собственная форма так и не написана

`models/chatter.js:94-125` открывает ядровый `mail.compose.message`.
В фазе 5 наш override `mail_compose_message.py` **удалён** как покрытый
ядром 19 (`default_subtype_xmlid` понимает ядро) — но это утверждение
живьём на 19 не проверялось. Если ядро 19 подтип не проставит, поток
`message` из чаттера перестанет работать. Плюс висит задача унификации с
кнопками Send Email из `velesagro_crm` / `email_document` (roadmap,
«To check / to do»).

### G6. Функции §11.2, которых нет ни в 15, ни в 19

- **C3/C4**: переключение Comment/Note и Send Message из композера канала
  (отступление 5 фазы 1). Сервер готов: `discuss.channel.message_post`
  прокидывает kwargs на запись-источник.
- **C5**: создание активности из канала записи. Синтетические
  activity-сообщения серверу известны (`models/mail_activity.py`), UI нет.

### G7. Поиск в сайдбаре по содержимому сообщений (§11.3) не реализован

Ни клиента, ни серверного эндпоинта, ни настройки «режим поиска» из §14
(в `models/res_config_settings.py` есть только таймаут попапа, ключ и
модель транскрипции). Требует полнотекстового индекса (`pg_trgm` + GIN),
дебаунса ~300 мс, обратного маппинга «сообщение → канал» и фильтрации по
правам. Это разрыв **относительно ТЗ**, а не регрессия порта.

### G8. Пагинация ленты Changes

`streams_changes_feed(before_id=...)` реализована серверно
(`models/discuss_channel.py:269`), клиент 15 её не использовал — лента
показывала последние 30 записей. Отмечено и в roadmap «To check / to do».

### G9. Мелочи, которые нужно переопределить при переписывании

- **Звук**: `messaging.soundEffects.newMessage` (`dm_02`) — API 15;
  в 19 сервис звуков другой (`js/notify_service.js:183-215`).
- **`sequence: 50.5`** у systray-колокола подбирался под набор модулей 15
  (`js/notify_systray.js:43-46`) — пересчитать под 19.
- **Классы ядровых кнопок чаттера** (`o_ChatterTopbar_buttonSendMessage`,
  `o_ChatterTopbar_buttonLogNote`) сохранялись ради xpath из
  `velesagro_crm` / `email_document` (`xml/chatter_topbar.xml:4-8`) —
  в 19 разметка чаттера другая, договорённость нужно переустановить.
- **Мост `notify_bridge.js`** больше не нужен: в 19 единый OWL 2 env.
- **`_syncUnreadCounter`** в обеих лентах — костыль 15, в 19 счётчик
  серверный (см. A12/A13).

---

## Расхождения с мобильным клиентом (референс семантики)

Мобильный клиент реализует те же фичи поверх `/streams/mobile/v1` и в
целом повторяет семантику легаси. Найденные отличия:

1. **Формат Changes**: мобильный оборачивает результат в
   `{'items': [...], 'has_more': ...}` (`api.py:381-404`), веб получал
   голый список. Серверный метод один и тот же — различие только в
   обёртке контроллера.
2. **Политика попапов Notify** совпадает с легаси до деталей: не-sticky
   с таймаутом (`app/lib/widgets/notify_popup.dart:55`), sticky-стек с
   пейджером, `popup_shown` по факту показа, `pending` из init
   (`app/lib/state/app_state.dart:34-52`). Отличие: мобильный **не** шлёт
   `popup_shown` батчем — отправляет по одному при показе; веб-версия
   батчила с дебаунсом 500 мс (`js/notify_service.js:159-177`).
   Для веба батч лучше сохранить.
3. **Bus**: мобильный по `discuss.channel/new_message` и
   `mail.record/insert` не разбирает Store-payload, а перезапрашивает
   ленту (`poll_service.dart:85,99`) — сознательное упрощение MVP.
   Веб-клиент 19 обязан применять Store-payload, иначе теряется смысл
   персональной адресной рассылки (`models/mail_thread.py:345-366`).
4. **Фильтры**: мобильный читает/пишет их одним эндпоинтом
   `/channel/filters` (`api.py:353`), внутри — те же
   `member._streams_get_filters()` и `channel.streams_set_filters()`.
   Веб зовёт `streams_set_filters` напрямую по ORM — контракт одинаковый.
5. **Канал Changes** в мобильном — отдельный экран, а не элемент списка
   каналов; `/v1/channels` отдаёт плоский список с `kind`, секции
   собирает клиент (отступление 3 фазы 6). Для веба сохраняется
   размещение в ядровой категории Channels (решение пользователя
   2026-08-18, roadmap «To check / to do»).
6. **`pending_popups` → `pending`**: имя ключа в init взято из
   `_streams_init_messaging` as-is (отступление 3 фазы 6) — веб-клиент 15
   использовал то же имя, расхождения нет.
