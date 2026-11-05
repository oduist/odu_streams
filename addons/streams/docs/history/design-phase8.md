# Фаза 8 — веб-UI на Odoo 19 (OWL 2 + Store)

Контракт исполнителей фазы 8. Источники фактов:
- `docs/design-phase8-research-core.md` — карта клиентского ядра 19 с
  рецептами расширения (обязательна к прочтению исполнителями);
- `docs/design-phase8-research-legacy.md` — чек-лист 58 фич легаси-клиента
  с серверными зависимостями и разрывами;
- `docs/roadmap.md` §6, §8.3, §11, §12 — требования;
- `static/legacy15/` — референс поведения (НЕ образец кода: фреймворк 15
  мёртв).

Правила: русские комментарии/докстринги в нашем коде, конвенции каталогов
mail-модулей 19 (`_model_patch.js`, `_patch.xml`, ...), никакой правки
`static/legacy15/`. Легаси в ассеты не подключать.

---

## 1. Принятые решения (дефолты; пользователь может отменить)

| # | Решение | Обоснование |
|---|---|---|
| Р1 | **Фильтрация потоков — серверная.** `_message_fetch` для record-каналов применяет сохранённые фильтры участника; тумблер на клиенте: RPC `streams_set_filters` → сброс кэша треда → refetch | Клиентский фильтр ломает пагинацию (FETCH_LIMIT=30 до фильтра) — риск 1 отчёта core |
| Р2 | **Третий тип композера НЕ вводим.** Chatter: Comment = ядровый quick-композер type='message' с переименованием и глушением email-семантики; Note = ядровый 'note'; Send Message (внешняя переписка) = полный композер `mail.compose.message` c `default_subtype_xmlid='streams.mt_message'` — как в 15 | Аудит ~6 сравнений `props.type` (риск 3) дороже и хрупче, чем паритет с 15 |
| Р3 | Категория сайдбара — одна своя: **Messages** (record-каналы). Личные Changes/Notifications — в ядровой Channels | Решение пользователя 2026-08-18 (roadmap To check); отчёт core предлагал три — отклонено на ревью |
| Р4 | «Отметить прочитанным» для лент Changes/Notify — **новый ORM RPC** `discuss.channel.streams_mark_read(last_message_id)` (тонкая обёртка над `member._mark_as_read`, образец — мобильный `api.py:333`) | Разрыв G1: маршрута 15 в 19 нет |
| Р5 | Notify-композер — **свой OWL-диалог** (не act_window): поиск получателей, чипы, sticky/timeout, голос | Паритет UX 15; форма ir.ui.view не даст ни поиска с дебаунсом, ни голоса |
| Р6 | Голос — ядровый `useVoiceRecorder()` + свой composer action / кнопка в диалоге; **свой рекордер не пишем**. Легаси-лимит 300 с уступает ядровому 60 с — принимаем ядровый | Отчёт core §8; меньше кода, mp3 вместо webm |
| Р7 | Рендер change-сообщений — ядровые `trackingValues` (бесплатно); своя разметка только в ленте личного Changes | Отчёт core §4.6 |
| Р8 | В объём фазы входят разрывы против ТЗ: C3 (Comment/Note в композере канала), C4 (Send Message из канала), C5 (активность из канала), D9/G8 (пагинация Changes) | Сервер готов; UI-цена мала на реестрах 19 |
| Р9 | Вне объёма: A18/G7 поиск по содержимому (§11.3/§14 — отдельная фаза с pg_trgm), унификация Send Email сторонних модулей, транскрипция UI сверх статуса «Transcribing…» | Отдельная серверная инфраструктура |
| Р10 | Bus-payload'ы Notify остаются лёгкими JSON (строки/числа), тела оборачиваются `markup()` на клиенте только после санитизации сервером | Риск 9: subscribe отдаёт JSON-копию |

## 2. Серверные доработки (в streams, до/вместе с WP1)

S1. `mail.message._message_fetch`: для record-каналов — домен минус потоки,
    выключенные у self-member (`streams_filters`); контекст-ключ
    `streams_unfiltered=True` отключает (используют мобильный контроллер и
    внутренние вызовы — `streams_mobile/controllers/api.py` проставить).
S2. `discuss.channel.streams_mark_read(last_message_id)` — ORM RPC, находит
    self-member, зовёт `_mark_as_read`, возвращает `{'unread': ...}`.
S3. `streams_notify_open_channel`: проверить достаточность Store-payload для
    появления канала в сайдбаре (self-member, is_pinned); при недостаче —
    расширить (разрыв G2).
S4. Проверить живьём: ядро 19 уважает `default_subtype_xmlid='streams.mt_message'`
    в `mail.compose.message` (утверждение фазы 5, G5). Если нет — вернуть
    мини-override.
S5. Тесты на S1/S2 в `tests/` (не ломая 97).

## 3. Пакеты работ (WP) — субагенты Opus, ревью архитектора после каждого

### WP1 «Фундамент» (блокирует остальные)
- `__manifest__.py`: секция assets (по отчёту core §9.3; glob'ы не должны
  захватить `static/legacy15/**` и `static/src/guest/**`).
- `static/src/core/common/thread_model_patch.js` — `channel_kind`,
  `res_model`, `res_id`, `streams_filters` (+дефолты), геттеры.
- `static/src/core/common/message_model_patch.js` — `streams_kind`,
  `stream_channel_ids` (Attr, голые id).
- `static/src/core/common/streams_core_service.js` — bus.subscribe на
  `streams.notify/new|update|counter`, `streams.changes/updated`.
- `static/src/core/common/store_service_patch.js` — глушение
  suggested/additional recipients для наших постов (риск 4: никакой
  автоматической внешней рассылки).
- Серверные S1, S2, S5 (+ правка streams_mobile: `streams_unfiltered`).
- Модель `mail.notify` на клиенте (`notify/notify_model.js`, Record,
  `static _name = "mail.notify"`).

### WP2 «Чаттер, канал, сайдбар» (после WP1)
- `chatter/web/chatter_patch.xml|.js`: Comment (переименованный ядровый),
  Note, Send Message (полный композер, ср. Р2/S4), Notify, Changes
  (визард подписки), Invite customer. Скрывать stream-кнопки на записях без
  mail.thread-чаттера не требуется (чаттер сам не рендерится).
- Композер чаттера type='message': скрыть строку получателей «To: followers»,
  плейсхолдер «Post an internal comment…» (паритет семантики 15).
- Thread actions (`discuss/core/common/thread_actions.js`): панель фильтров
  (5 тумблеров, оптимистичный апдейт + RPC + refetch по Р1), Notify,
  Invite customer, Schedule activity (C5 — act_window
  `mail.activity.schedule` по res_model/res_id канала); condition —
  `channel_kind === 'record'`.
- Композер record-канала: переключатель Comment/Note (C3; свой composer
  action или патч, `subtype_xmlid` через постпараметры), кнопка Send
  Message (C4 → полный композер записи-источника).
- Сайдбар: категория Messages (`discuss_app_model_patch.js` +
  `_computeDiscussAppCategory` — только `record`; Р3), serverStateKey
  `is_discuss_sidebar_category_streams_open`; личные каналы — в ядровой
  Channels.
- `message_patch.xml`: скрыть ссылку «on <документ>» в record-канале.
- SCSS минимально.

### WP3 «Notify» (после WP1, параллельно WP2)
- `notify/streams_notify_service.js`: состояние (counter, channelId,
  default_timeout, popups, stickyIndex, mute), init из глобального Store
  `streams_notify` (E1), pending-попапы, батч `streams_notify_popup_shown`
  (дебаунс 500 мс), звук (ядровый sound-сервис 19, мастер-вкладка; фолбэк
  Audio), Mute через `set_res_users_settings`.
- `notify/streams_notify_container.js|.xml|.scss` — main_components,
  sequence 110, transient+sticky-стек с пагинатором, пауза по hover.
- `notify/streams_notify_composer.js|.xml` — диалог (Р5): поиск получателей
  (name_search share=false, дебаунс 300, лимит 8), чипы, вложения
  (useAttachmentUploader → `/mail/attachment/upload`, pending-паттерн;
  проверить формат ответа — разрыв G4, при несовместимости — крошечный свой
  маршрут), голос (Р6, форс sticky + блокированный чекбокс), timeout 3..300,
  send/reply.
- `systray/streams_notify_menu.js|.xml` — колокол слева от Discuss, бейдж
  99+, клик → `streams_notify_open_channel` (S3) и переход в канал.
- Лента Notifications (`notify/streams_notify_feed.js|.xml`): вкладки
  Received/Sent, Load more, прочитанность по доскроллу (IntersectionObserver,
  только Received) → `streams_notify_mark_read`, живые вставки/патчи по
  bus, Reply, Mute, New notification; подмена контента Discuss для
  `channel_kind === 'notifications'` (xpath по `mail.Discuss`/DiscussContent).

### WP4 «Changes» (после WP1, параллельно WP2/WP3)
- `changes/streams_changes_feed.js|.xml|.scss`: RPC `streams_changes_feed`,
  «поле: было → стало», клик по записи → форма, прочитанность по доскроллу →
  `streams_mark_read` (Р4), живой рефреш по `streams.changes/updated`,
  **пагинация before_id / Load more** (Р8), счётчик — серверный
  `message_unread_counter` (без костыля `_syncUnreadCounter`).
- Подмена контента Discuss для `channel_kind === 'changes'`; ядровый
  ThreadView для changes/notifications не строится (A19).

### WP5 «Тесты и живая проверка» (тест-субагенты; после WP2–WP4)
- Hoot: `static/tests/` + mock-модели (`mail.notify`, патчи discuss.channel
  /mail.message; `defineStreamsModels()`); python-обёртка `browser_js` по
  образцу `web/tests/test_js.py` (HOOTCommon), фильтр по модулю.
- Tours: chatter-кнопки → пост comment/note; фильтры канала; Notify
  end-to-end (отправка → попап → канал); Changes (изменение поля → лента).
  Запуск `start_tour` из HttpCase.
- Полный серверный прогон streams + streams_mobile (не меньше 97 зелёных
  плюс новые S5).
- Живая проверка в streams19 по DOM (образец — проверки фаз 1–4 в roadmap).

## 4. Порядок и параллельность

WP1 → (WP2 ∥ WP3 ∥ WP4) → WP5. Конфликты файлов между WP2–WP4 исключены
раскладкой каталогов; манифестные glob'ы заводит WP1 сразу на все каталоги.
Каждый WP завершается ревью архитектора (диффом), только потом следующий.

## 5. Критерии приёмки фазы

1. Все фичи A–G из design-phase8-research-legacy.md со статусами ✅/✳️
   воспроизведены; разрывы Р8 закрыты; Р9 — зафиксированы в roadmap как
   отложенные.
2. Инварианты модуля не нарушены (AGENTS.md): никакой автоподписки, никаких
   email внутренним, change не трогает unread.
3. Hoot + tours зелёные в среде; полный python-прогон зелёный.
4. Живая DOM-проверка сценариев фаз 1–3 на 19 задокументирована в roadmap.
