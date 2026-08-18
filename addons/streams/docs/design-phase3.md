# streams — Дизайн Фазы 3 (Notifications)

Реализует §4.5, §12 целиком, кнопку **Notify** из §11.1/§11.2, иконку навбара
§11.4 и настройки §14 (таймаут попапа 10 с, ключ OpenAI) ТЗ (`roadmap.md`).

Фазы 1a/1b сделаны, фаза 2 (Changes) шла параллельно с подготовкой этого
дизайна. Из уже готового переиспользуется: `channel_kind` + `owner_user_id` на
`mail.channel` (`models/mail_channel.py:16-34`), форк `_compute_message_unread`
(`models/mail_channel.py:307-367`), `channel_info()` с нашими ключами
(`:142-164`), паттерн патчей messaging-моделей (`static/src/models/*.js`) и
паттерн кнопки чаттера через `t-inherit` + `registerInstancePatchModel`
(`static/src/xml/chatter_topbar.xml:40-51`, `static/src/models/chatter.js`).

Порядок работ: сервер + тесты (раздел А) → UI (раздел Б) → браузерный прогон
(раздел В). Не начинай UI, пока серверные тесты не зелёные.

## Решения пользователя по развилкам (2026-08-18, не пересматривать)

- Транскрипция: **queue_job + крон-страховка** (как в разделе А8).
- Звук: один звук на все уведомления **плюс персональный тумблер Mute**
  (см. Б3: `res.users.settings.is_streams_notify_sound_muted`).
- Удаление: автор может удалить своё уведомление **в любой момент** —
  ACL из А3 остаётся как есть, окна и запретов не вводим.
- Формат аудио — «как записалось» (без ffmpeg); ключ OpenAI — существующий
  параметр `openai_api_key`; модель по умолчанию `whisper-1`; форс sticky —
  только при голосе в самом уведомлении (ответ без голоса наследует, но может
  снять); попапы во всех вкладках, звук только в мастер-вкладке; лимиты голоса
  5 мин / 25 МБ; канал Notifications — в ядровой категории Channels, основной
  вход — иконка навбара.

**Координация с фазой 2 (обязательно прочитать до первой правки).** Фазы 2 и 3
трогают одни и те же четыре точки. Кто вторым — правит поверх, а не
переписывает:

| Точка | Фаза 2 | Фаза 3 |
|---|---|---|
| `mail_channel._compute_message_unread` | ветка `channel_kind='changes'` | ветка `channel_kind='notifications'` |
| частичный UNIQUE по личным каналам | создаёт индекс на `(channel_kind, owner_user_id)` | переиспользует его же, своего не заводит |
| замена ThreadView по `channel_kind` в Discuss | компонент ленты Changes | компонент ленты Notifications; **один общий xpath-патч `mail.Discuss`, `t-if` по kind** |
| `chatter_topbar.xml` | кнопка Changes | кнопка Notify (xpath `position="after"` от Send Message) |
| `__manifest__.py` (assets, version) | 15.0.1.2.0 | 15.0.1.3.0 |

---

## Карта фактов (проверено по исходникам)

### Ядро Odoo 15 (`~/Dev/odoo_15`)

**Systray и навбар**
- `mail/static/src/services/systray_service/systray_service.js:20-25` — mail
  добавляет `mail.MessagingMenu` и `mail.RtcActivityNotice` в
  `registry.category('systray')` **без `sequence`**, из `start()` legacy-сервиса
  после `messagingCreatedPromise` (`:19`).
- `web/static/src/core/registry.js:60` — sequence по умолчанию **50**;
  `:112-113` — `getEntries()` сортирует по возрастанию (числовое вычитание, то
  есть дробные значения допустимы).
- `web/static/src/webclient/navbar/navbar.js:99-105` — геттер `systrayItems`
  делает `.reverse()` (строка 104) ⇒ **больший sequence = левее**;
  `:67` — навбар перерисовывается по событию `UPDATE` реестра, поэтому
  регистрация из любого момента загрузки ассетов безопасна.
- Занятые значения: `web.user_menu` 0 (`user_menu.js:56`), `SwitchCompanyMenu`
  1 (`switch_company_menu.js:51`), `veles_custom_reports` **49**
  (`custom_reports_systray.js:15-19`), mail `MessagingMenu`/`RtcActivityNotice`
  **50**, mail Activity menu 50 (`mail/static/src/js/systray/systray_activity_menu.js:196`),
  `connect_messagebox` **51** (`messagebox_systray.js:7`, push `:64`),
  debug-меню 100.
- Legacy-виджеты попадают в тот же OWL-реестр через адаптер
  `web/static/src/legacy/systray_menu_item.js:35` (sequence берётся из
  `Widget.prototype.sequence`), так что «столкнуться» с connect_messagebox можно
  только выбрав ровно 51.
- Плоский wowl-компонент systray — образец `switch_company_menu.js:11-51`
  (`useService`, `registry.category("systray").add(name, item, {sequence})`).

**Шина**
- `bus/models/bus.py:132-133` — `_sendone(channel, notification_type, message)`;
  `:97-110` — `_sendmany`; `:54-58` `channel_with_db` — каналом может быть и
  запись (`(db, model, id)`), и строка.
- `mail/controllers/bus.py:26-28` — сервер сам добавляет в подписку
  `request.env.user.partner_id` и все каналы пользователя (`:34-35`); клиенту
  добавлять партнёрский канал не нужно.
- `mail/static/src/models/messaging_notification_handler/messaging_notification_handler.js:63-135`
  — switch по типам; `:133-134` `default` → `_handleNotification(message)`,
  объявленный абстрактным на `:141-146`. Это штатная точка расширения ядра для
  чужих bus-типов.
- `_handleNotificationSimpleNotification` (`:481-493`) показывает тост через
  **legacy** `services.notification.notify`, не через wowl `add`.

**Тосты и главные компоненты**
- `web/static/src/core/notifications/notification_service.js:26-73`: `add()`
  `:42`, автозакрытие 4000 мс жёстко зашито `:9`+`:55-57`, контейнер
  регистрируется в `registry.category("main_components")` `:33-36`, сам сервис —
  `:73`.
- `web/static/src/core/notifications/notification.js:37-66` — props тоста:
  `message`, `title`, `type`, `messageIsHtml`, `className`, `buttons`,
  `onClose`. **Вставить OWL-компонент внутрь тоста нельзя**; ядро само называет
  это ограничением и обходит его строкой HTML
  (`messaging_notification_handler.js:730-731`).
- `web/static/src/core/main_components_container.js:9` — все компоненты из
  категории `main_components` монтируются поверх webclient. Это и есть
  механизм наложения собственных попапов.
- Диалоги: `web/static/src/core/dialog/dialog_service.js:32` — сервис `dialog`,
  `dialog.add(Component, props)`.

**Звук**
- `mail/static/src/audio/` — `ting`, `dm_01`, `dm_02`, `channel_01_in/out`,
  `channel_04_out`, `call_02_in_`, `share_02`; каждый в `.mp3` и `.ogg`.
- `mail/static/src/models/sound_effect/sound_effect.js:19-34` — `play({loop,
  volume})`, ленивый `new Audio()` `:24`, выбор `.ogg`/`.mp3` по
  `canPlayType` `:25`, путь `/mail/static/src/audio/` `:68`.
- `mail/static/src/models/sound_effects/sound_effects.js:29-32` — слот
  `newMessage` (`dm_02`) объявлен и **нигде в 15 не используется** — свободен.
- `bus/static/src/js/services/bus_service.js:110-119` `_beep()` (файл `ting`),
  вызывается из `sendNotification()` `:67-90` и только в мастер-вкладке
  (`isMasterTab()` `:69`, `:86`).

**Вложения**
- `mail/controllers/discuss.py:238-276` — `/mail/attachment/upload`
  (`type='http'`, POST): `ufile`, `thread_id`, `thread_model`, `is_pending`.
  Проверка членства делается **только** для `thread_model == 'mail.channel'`
  (`:240-242`); при `is_pending` вложение создаётся как
  `res_model='mail.compose.message'`, `res_id=0` (`:249-255`).
- Клиент: `mail/static/src/components/file_uploader/file_uploader.js:71-79`
  (FormData: `csrf_token`, `is_pending`, `thread_id`, `thread_model`, `ufile`),
  `:112-116` — `fetch('/mail/attachment/upload')`.
- `odoo/addons/base/models/ir_attachment.py:439-481` — `check()`: чтение
  вложения требует **чтения связанной записи**, create/unlink — **записи**;
  `:455` — вложение с `res_id=0` доступно только своему создателю (это и есть
  механика pending).
- `mail/models/mail_thread.py:1731-1735` — канонический перепривязчик pending →
  реальная запись (`res_model == 'mail.compose.message' and create_uid == uid`
  → `write({'res_model': ..., 'res_id': ...})`).
- `web/controllers/main.py:1457-1459` — `/web/binary/upload_attachment`, ответ
  JSONP-обёрткой `<script>`; для нашего случая не годится, используем
  `/mail/attachment/upload`.

**Голос**
- `MediaRecorder` **не встречается в Odoo 15 нигде** (0 совпадений по
  `addons/` и `odoo/`). Готового рекордера нет: `getUserMedia` есть только для
  RTC и «эхо-превью» микрофона
  (`mail/static/src/models/media_preview/media_preview.js:73`), громкость меряет
  `mail/static/src/utils/media_monitoring/media_monitoring.js:34`.
- Плеера для аудио-вложений тоже нет: `mail/static/src/models/attachment/attachment.js:253-261`
  `_computeIsVideo` знает только `audio/mpeg`, `video/x-matroska`, `video/mp4`,
  `video/webm`; `audio/webm`, `audio/ogg`, `audio/mp4` не `isViewable`
  (`:277-279`), рендер идёт тегом `<video>`
  (`components/attachment_viewer/attachment_viewer.xml:59-61`).

**Прочее**
- `mail/models/res_users.py:132-150` `_init_messaging` — единый payload старта
  клиента; `mail/static/src/models/messaging_initializer/messaging_initializer.js:48`
  и `:76-91` — `_init(data)` деструктурирует известные ключи, но патч получает
  весь объект (в streams уже есть патч `_initResUsersSettings`,
  `static/src/models/messaging_initializer.js:8-25`).
- `mail/static/src/models/discuss/discuss.js:205-230` — `openThread(thread)`,
  открытие Discuss действием `mail.action_discuss` с
  `active_id = '<model>_<id>'`; `mail/static/src/widgets/discuss/discuss.js:38-40`
  — этот же `active_id` читается из `action.context`.
- `mail/models/mail_channel_partner.py:28` — `is_pinned` (default True);
  `mail/models/res_partner.py:131-145` — в `_init_messaging` попадают только
  запиненные каналы, где пользователь участник.
- `mail/models/mail_thread.py:2034-2076` — ядровый `message_notify`: создаёт
  `mail.message` с `message_type='user_notification'`. Мы им **не** пользуемся
  (§12.1: уведомление не `mail.message`), но помним: наш классификатор уже
  отбрасывает `user_notification` (`models/mail_message.py:94-95`).

### addons_veles

- `bus_actions/models/bus_actions.py:31-33` — `_personal_channel(user)` =
  `bus_actions_<uid>`; `:53-60` — **`signal(name, payload, user=None)`**: тип
  сообщения произвольный, канал персональный. `:42-50` — `notify()` (тип
  `notify`), `:36-39` — `reload_view`, `:63-76` — `open_record`.
- `bus_actions/static/src/js/bus_actions.js:5-6` — каналы; `:16-20` — сервис сам
  делает `addChannel(PERSONAL_CHANNEL)`, `addChannel(COMMON_CHANNEL)`,
  `onNotification`, `startPolling`; `:23-39` — жёсткий if/else по трём типам,
  **реестра чужих обработчиков нет**, неизвестный тип просто игнорируется;
  `:72` — регистрация сервиса.
- Принятый в репозитории способ расширения — свой listener на том же канале:
  `connect_messagebox/static/src/js/messagebox_systray.js:20-22` + фильтр по
  типу `:49` (шлётся из `connect_messagebox/models/connect_messagebox_message.py:371-372`
  через `bus.actions.signal`), и `velesagro_timeline/static/src/timeline/timeline_feed.js:118-135`
  (подписка в `onMounted`, обязательная отписка `busService.off("notification", this)`
  в `onWillUnmount`).
- `queue_job` вендорится в `addons_veles/queue_job/`. Реальные потребители:
  `velesagro_crm` (`models/crm_lead_ai_next_step.py:58-62`, `:67-71`,
  `models/connect_messagebox_ai.py:25-29`, каналы/ретраи —
  `data/queue_job_function_data.xml`) и `supply_stock`
  (`wizard/print_label.py:82`, `models/shipment.py:1267`). Jobrunner требует
  `server_wide_modules = web,queue_job` в `odoo.conf` контейнера — корневой
  `AGENTS.md:249-258`, `queue_job/README.rst:111`.
- Вызов OpenAI из Odoo: `velesagro_crm/models/crm_lead_ai_next_step.py:23`
  (`https://api.openai.com/v1/responses`), `:335-361` — `requests.post(...,
  timeout=60)` и лестница ошибок: сетевая/429/5xx → `RetryableJobError`,
  4xx → `UserError`; ключ проверяется до постановки задания `:85-86`.
- Ключ уже есть в системных параметрах: `velesagro_crm/models/res_config_settings.py:22-24`
  — `openai_api_key` (`config_parameter='openai_api_key'`), seed пустым
  значением под `noupdate="1"` в `data/ir_config_parameter_data.xml:6-10`.
- Крон с минутным интервалом — образец `ai_chat/data/ai_chat_data.xml:22-32`
  (5 minutes, `numbercall -1`, `doall=False`).
- Собственных OWL-сервисов в репозитории два: `bus_actions/static/src/js/bus_actions.js:8-72`
  и `jkl_develop/static/src/force_reload/force_reload_service.js:6-55`
  (второй откладывает подписку до `env.bus.on("WEB_CLIENT_READY")` — так
  надёжнее).
- `MediaRecorder`/`getUserMedia` в addons_veles нет вовсе; транскрипции/Whisper
  в репозитории нет (в `doc_triage_service` — только текстовый OpenAI).

---

## Решения (и почему так)

1. **Уведомление — не `mail.message`.** Две новые модели без наследования
   `mail.thread`: у них нет чаттера, они не создают каналов записей и не
   проходят через классификатор потоков. Побочно это снимает риск попасть в
   `_streams_link_existing_channels` (`models/mail_message.py:120-160`).

2. **Доставка — через `bus.actions.signal`, а не свой `_sendone`.** AGENTS.md
   требует переиспользовать `bus_actions`, и `signal()` (`bus_actions.py:53-60`)
   — ровно обобщённый отправитель произвольного типа в персональный канал.
   Свой JS-обработчик вешаем как это уже делают connect_messagebox и
   velesagro_timeline: `bus_service.onNotification` + фильтр по типу. Свои типы:
   `streams.notify/new`, `streams.notify/update`, `streams.notify/counter`
   (тип `notify` занят самим bus_actions — не использовать).
   Партнёрский канал ядра (`mail/controllers/bus.py:26-28`) не берём: он
   принадлежит messaging-слою, а уведомление сознательно вне него.

3. **Попапы — собственный OWL-сервис + компонент в `main_components`, не
   notification-сервис.** Тост в 15 не принимает компонент
   (`notification.js:37-66`), таймаут у него константа 4000 мс
   (`notification_service.js:9`) и не настраивается per-notification, а нам
   нужны: произвольный таймаут (§12.2), стек sticky с переключением (§12.4),
   плеер и кнопка Reply внутри. Через `messageIsHtml` это было бы мёртвым HTML
   без обработчиков. Копируем скелет самого `notification_service.js`
   (EventBus + контейнер в `main_components`), меняя содержимое.

4. **Иконка навбара — wowl-компонент в systray registry с `sequence: 50.5`.**
   OWL-путь идиоматичнее (весь ядровый systray 15 в реестре; legacy-виджеты
   туда же затягивает адаптер) и в addons_veles легко перепроверяем.
   Сортировка числовая (`registry.js:112-113`), порядок в навбаре реверсный
   (`navbar.js:104`) ⇒ 50.5 ставит нашу иконку **вплотную слева от Discuss**
   (50) и не конфликтует ни с connect_messagebox (51), ни с
   veles_custom_reports (49). Регистрируем статически при загрузке ассета:
   навбар перерисуется по `UPDATE` (`navbar.js:67`), ждать messaging не нужно —
   счётчик мы берём из своего сервиса, а не из messaging-моделей.

5. **Голос — свой рекордер, загрузка штатным маршрутом.** В 15 рекордера нет,
   писать с нуля. Формат — первый поддерживаемый из
   `audio/webm;codecs=opus` → `audio/ogg;codecs=opus` → `audio/mp4`
   (`MediaRecorder.isTypeSupported`), mimetype сохраняем на вложении. Загрузка —
   `/mail/attachment/upload` с `thread_model='mail.notify'`, `thread_id=0`,
   `is_pending=true` (проверка членства там только для `mail.channel`,
   `discuss.py:240-242`), затем серверная перепривязка по образцу
   `mail_thread.py:1731-1735`. Плеер — свой `<audio controls>` c
   `/web/content/<id>`; ядровый `_computeIsVideo` **не патчим** (attachment.js
   — общий для всего mail, ломать чужие ленты нельзя).

6. **Транскрипция — `queue_job`, крон как страховка.** §12.3 требует «текст
   доезжает через несколько секунд»; минимальный шаг `ir.cron` — минута, то
   есть кроном требование не выполняется в принципе. queue_job в репозитории
   уже боевой (velesagro_crm гоняет через него OpenAI с `RetryableJobError`),
   лестница обработки ошибок готова к копированию
   (`crm_lead_ai_next_step.py:335-361`). Добавляем `ir.cron` раз в 5 минут,
   который подбирает записи, зависшие в `transcript_state='queued'` дольше 10
   минут: это и страховка от выключенного jobrunner (в Oduflow-средах его надо
   включать руками, `AGENTS.md:249-258`), и обычный retry-sweeper.

7. **Прочитанность — по скроллу, своим RPC-фидом.** Один в один паттерн фазы 2:
   лента канала Notifications не состоит из `mail.message`, значит стандартный
   ThreadView и `_channel_seen` к ней неприменимы; свой компонент +
   IntersectionObserver + `streams_notify_mark_read(ids)`.

8. **Попапы «накопившиеся» отдаются в `_init_messaging`,** а не отдельным RPC:
   это один и тот же payload старта клиента, лишний round-trip не нужен, а
   патч `messaging_initializer` в streams уже есть. `popup_shown` ставится не
   при выдаче, а после фактического показа (`streams_notify_popup_shown(ids)`)
   — иначе падение вкладки съедает уведомление.

---

## А. Сервер

### А1. `mail.notify`

| Поле | Тип | Замечания |
|---|---|---|
| `author_id` | m2o `res.users`, required, index, default `env.user`, ondelete `restrict` | §4.5 |
| `body` | Html | композер шлёт текст, сервер прогоняет `tools.plaintext2html`; редактор и `@mention` — вне фазы |
| `attachment_ids` | m2m `ir.attachment` (`mail_notify_attachment_rel`) | |
| `voice_attachment_id` | m2o `ir.attachment`, ondelete `set null` | |
| `voice_duration` | Integer, сек | из рекордера; нужно для подписи под плеером |
| `transcript` | Text | |
| `transcript_state` | Selection `none`/`queued`/`done`/`failed`, default `none` | |
| `res_model` / `res_id` | Char / Integer, index по паре | опционально (§12.2) |
| `record_name` | Char | снимок `display_name` на момент отправки: лента не должна ходить по чужим моделям ради имени |
| `is_sticky` | Boolean | |
| `timeout` | Integer, default из `streams.notify_timeout` | |
| `parent_id` | m2o `mail.notify`, ondelete `set null`, index | цепочка §12.6 |
| `recipient_ids` | o2m `mail.notify.recipient` | |

`_order = 'id desc'`. Дата — `create_date`.

Правила модели:
- `create`/`write`: `voice_attachment_id` ⇒ `is_sticky = True` принудительно
  (§12.3), даже если клиент прислал False;
- `timeout` зажимается в `[3, 300]`; при `is_sticky` значение игнорируется на
  клиенте, но в базе остаётся (ответ может снять sticky и унаследовать таймаут);
- получатели — только внутренние (`not user.share`, `active`); попытка добавить
  share-пользователя → `ValidationError` c английским текстом;
- `unlink` доступен только автору (см. ACL); каскадом уходят recipient-строки.

### А2. `mail.notify.recipient`

| Поле | Тип |
|---|---|
| `notify_id` | m2o `mail.notify`, required, ondelete cascade, index |
| `user_id` | m2o `res.users`, required, ondelete cascade, index |
| `partner_id` | related `user_id.partner_id`, store, index (адресация шины и аватар в ленте) |
| `read_date` | Datetime |
| `popup_shown` | Boolean, default False |

SQL unique `(notify_id, user_id)`.

`write`: если пишет не автор исходного уведомления — разрешены только
`read_date` и `popup_shown` (иначе `AccessError`). Повторный `mark_read` не
перетирает уже проставленный `read_date`.

### А3. ACL

`security/ir.model.access.csv`:
- `mail.notify`: `base.group_user` — read/write/create = 1, unlink = 1
  (ограничение по автору даёт ir.rule);
- `mail.notify.recipient`: `base.group_user` — read/write/create/unlink = 1.

`security/streams_security.xml` (дописать в существующий файл):
- «Notify: read own or received», только `perm_read`:
  `['|', ('author_id','=',user.id), ('recipient_ids.user_id','=',user.id)]`;
- «Notify: manage own», `perm_write/create/unlink`:
  `[('author_id','=',user.id)]`;
- «Notify recipient: read own or as author», `perm_read`:
  `['|', ('user_id','=',user.id), ('notify_id.author_id','=',user.id)]`;
- «Notify recipient: mark own», `perm_write`: `[('user_id','=',user.id)]`
  (плюс правило автора на write, чтобы автор мог править свои рассылки);
- «Notify recipient: manage as author», `perm_create/unlink`:
  `[('notify_id.author_id','=',user.id)]`.

Вложения: `res_model='mail.notify'`, `res_id=<id>` ⇒ доступ к файлу
автоматически повторяет доступ к уведомлению (`ir_attachment.py:439-481`).
Отдельных правил на `ir.attachment` не заводим.

### А4. Личный канал Notifications

Хелпер на `mail.channel` рядом с существующими:

```python
def _streams_get_notifications_channel(self, user=None):
    """Личный служебный канал уведомлений (§12.5). Ленивое создание."""
```

- `channel_kind='notifications'`, `owner_user_id=user`, `channel_type='channel'`,
  `public='private'`, `name='Notifications'`, единственный участник — сам
  пользователь (`is_pinned=True`, иначе канал не попадёт в `_init_messaging`,
  `res_partner.py:131-145`);
- создаётся лениво: при первом полученном или отправленном уведомлении и по
  явному `streams_notify_open_channel()` (клик по иконке навбара);
- уникальность — тем же частичным индексом на `(channel_kind, owner_user_id)`,
  который заводит фаза 2 (см. таблицу координации).

`channel_info()` уже отдаёт `channel_kind` (`models/mail_channel.py:158`) —
клиенту этого достаточно, чтобы подменить ленту.

### А5. Публичный API (RPC)

Все методы — на `mail.notify`, внутри `sudo()` только там, где нужно писать
чужие recipient-строки; проверки прав явные.

```
streams_notify_send(vals)                # -> {'id': int}
streams_notify_reply(parent_id, vals)    # -> {'id': int}
streams_notify_feed(box='received', limit=30, before_id=None)   # -> [item]
streams_notify_mark_read(notify_ids)     # -> {'counter': int}
streams_notify_popup_shown(notify_ids)   # -> True
streams_notify_open_channel()            # -> channel_info() личного канала
```

`vals` формы отправки (§12.2): `user_ids` (список id внутренних пользователей),
`body` (текст), `attachment_ids`, `voice_attachment_id`, `voice_duration`,
`is_sticky`, `timeout`, `res_model`, `res_id`.

`streams_notify_send`:
1. валидация получателей (внутренние, активные, непустой список);
2. перепривязка pending-вложений (`res_model='mail.compose.message'`,
   `res_id=0`, `create_uid=uid`) на `('mail.notify', id)` — копия
   `mail_thread.py:1731-1735`;
3. `record_name` = `display_name` записи под sudo, если пришли `res_model/res_id`
   и модель существует в реестре;
4. постановка задания транскрипции, если есть голос и ключ (А8);
5. get-or-create каналов Notifications автора и каждого получателя;
6. bus-рассылка `streams.notify/new` каждому получателю (А6).

`streams_notify_reply` (§12.6): получателем становится **только**
`parent.author_id`; `is_sticky`/`timeout` по умолчанию наследуются из родителя и
могут быть переопределены в `vals`; глубина цепочки не ограничивается, но
рекурсивная проверка «родитель существует и я его автор или получатель» —
обязательна.

`streams_notify_feed(box)`:
- `received`: свои recipient-строки, `id desc`, поля уведомления +
  `read_date`, `popup_shown`;
- `sent`: свои уведомления + `recipients: [{'user_id', 'name', 'read_date'}]`
  (§12.5, «прочитано в 14:32» рисует клиент);
- элемент (общая форма, она же payload шины):

```python
{
  'id': 12, 'date': '2026-08-18 09:12:41',
  'author': {'id': 3, 'name': 'Anna K.'},
  'body': '<p>...</p>',
  'is_sticky': False, 'timeout': 10,
  'res_model': 'res.partner', 'res_id': 42, 'record_name': 'BIOMA FOOD',
  'attachments': [{'id': 7, 'name': 'spec.pdf', 'mimetype': 'application/pdf', 'size': 12345}],
  'voice': {'id': 8, 'mimetype': 'audio/webm', 'duration': 14},
  'transcript': False, 'transcript_state': 'queued',
  'parent_id': False,
  'read_date': False,                    # только в received
  'recipients': [...],                   # только в sent
}
```

`streams_notify_mark_read` — ставит `read_date` (только если пусто), шлёт автору
`streams.notify/update` с новым `read_date` и себе `streams.notify/counter`
(синхронизация вкладок и бейджа).

### А6. Шина

```python
self.env['bus.actions'].signal('streams.notify/new', payload, user=recipient)
self.env['bus.actions'].signal('streams.notify/update', patch, user=user)
self.env['bus.actions'].signal('streams.notify/counter', {'counter': n}, user=user)
```

- `new` — полный payload элемента (см. А5) + `counter`;
- `update` — `{'id', ...изменившиеся ключи}`: `transcript`/`transcript_state`
  после транскрипции, `read_date` автору после прочтения;
- `counter` — только число, для бейджа.

Рассылка идёт **после** коммита (bus_actions использует ядровый `_sendone`,
который сам вешает `NOTIFY imbus` на postcommit, `bus.py:111-130`) — специально
ничего делать не нужно.

Проверок прав на записи здесь, в отличие от `_streams_broadcast`
(`models/mail_thread.py:286-352`), не требуется: уведомление адресное, право на
него даёт сама recipient-строка.

### А7. Голос и вложения

- Приём файла — штатный `/mail/attachment/upload` (своего контроллера не
  заводим): `thread_model='mail.notify'`, `thread_id=0`, `is_pending=true`.
- Ограничения проверяются на сервере в `streams_notify_send`: голос — только
  mimetype из белого списка (`audio/webm`, `audio/ogg`, `audio/mp4`,
  `audio/mpeg`, `audio/wav`), размер ≤ 25 МБ (лимит OpenAI), длительность ≤ 5
  минут по `voice_duration`. Нарушение → `UserError` с английским текстом.
- Осиротевшие pending-вложения (форму открыли, записали, закрыли) подбирает тот
  же крон из А8: `res_model='mail.compose.message'`, `res_id=0`, старше суток —
  удалять **не** в этой фазе (ядро их тоже не чистит); только логировать
  количество.

### А8. Транскрипция

Модуль получает `queue_job` в `depends`.

```python
def _streams_enqueue_transcription(self):
    """Голос отправляется сразу, текст доезжает (§12.3)."""
    self.with_delay(
        priority=20,
        identity_key='streams.notify.transcript.%s' % self.id,
        description='Transcribe voice notification %s' % self.id,
    )._job_transcribe()
```

- Ставится только при `voice_attachment_id` **и** непустом ключе; иначе
  `transcript_state` остаётся `none` (§12.3 «ключа нет — просто аудио»).
- `data/queue_job_function_data.xml` — запись `queue.job.function` для
  `mail.notify._job_transcribe` с `edit_retry_pattern` `{1: 60, 3: 300, 5: 1800}`
  (копия `velesagro_crm/data/queue_job_function_data.xml`), `noupdate="1"`.
- `_job_transcribe`:
  - `POST https://api.openai.com/v1/audio/transcriptions`, multipart
    (`file=(name, raw, mimetype)`, `model=<streams.transcription_model>`,
    `response_format='json'`), `timeout=(10, 120)`, заголовок
    `Authorization: Bearer <openai_api_key>`;
  - сетевая ошибка / 429 / ≥500 → `RetryableJobError`;
  - 4xx (кроме 429) и невалидный JSON → `transcript_state='failed'`, текст
    ошибки в `_logger.warning`, поля под ошибку не заводим;
  - успех → `transcript`, `transcript_state='done'`, bus `streams.notify/update`
    получателям **и** автору.
- `ir.cron` `ir_cron_streams_notify_transcribe`, 5 minutes, `numbercall=-1`,
  `doall=False` (образец `ai_chat/data/ai_chat_data.xml:22-32`): забирает
  `transcript_state='queued'` старше 10 минут и переставляет задание. Это же
  спасает среды без `server_wide_modules = web,queue_job`.

### А9. Счётчик, канал, старт клиента

- **Счётчик** = число своих recipient-строк с `read_date IS NULL`. Один SQL,
  метод `mail.notify._streams_notify_counter(user)`.
- **Unread канала Notifications**: ветка в форке
  `mail_channel._compute_message_unread` (`models/mail_channel.py:307-367`) —
  для `channel_kind='notifications'` счётчик берётся из `mail.notify.recipient`,
  а не из сообщений (сообщений в этом канале не бывает вовсе).
- **`_init_messaging`** (override `res.users`, рядом с
  `models/res_users.py`): добавить ключ

```python
values['streams_notify'] = {
    'counter': n,
    'channel_id': channel_id_or_False,     # без ленивого создания
    'pending': [...],                      # popup_shown=False, не старше 7 дней, limit 20
}
```

  Порядок в `pending` — по возрастанию id (стек показывается в хронологии).

### А10. Настройки (§14)

`models/res_config_settings.py` + `views/res_config_settings_views.xml`
(`app_settings_block`, `data-key="streams"`, `groups="base.group_system"`):

| Поле | `config_parameter` | Default |
|---|---|---|
| `streams_notify_timeout` (Integer) | `streams.notify_timeout` | 10 |
| `streams_openai_api_key` (Char) | `openai_api_key` | «» |
| `streams_transcription_model` (Char) | `streams.transcription_model` | `whisper-1` |

Ключ **не дублируем новым параметром**: `openai_api_key` уже живёт в базе
(`velesagro_crm/models/res_config_settings.py:22-24`), поэтому имя поля другое,
а параметр тот же. Seed `data/ir_config_parameter_data.xml` — только
`streams.notify_timeout` и `streams.transcription_model`, под
`<data noupdate="1">`; для ключа не создаём ничего.

### А11. Тесты (обязательные)

1. Отправка: создаются recipient-строки; автор и получатель читают
   уведомление, третий пользователь получает `AccessError`.
2. Получатель может писать только `read_date`/`popup_shown`; попытка изменить
   `body` — `AccessError`.
3. Голос форсирует `is_sticky=True`, даже если прислали `False` (§12.3).
4. `timeout` по умолчанию берётся из `streams.notify_timeout`; изменение
   параметра меняет дефолт новой отправки.
5. Вложения: pending (`mail.compose.message`, `res_id=0`) перепривязываются на
   `mail.notify`; получатель читает вложение, посторонний — нет.
6. Ответ (§12.6): получатель ровно один — автор родителя; sticky/timeout
   наследуются; переопределение работает; цепочка из трёх звеньев строится.
7. `mark_read`: `read_date` ставится один раз, повтор не перетирает; в
   `streams_notify_feed('sent')` автор видит время прочтения.
8. Счётчик: два непрочитанных → 2; после `mark_read` → 0; `message_unread_counter`
   личного канала Notifications совпадает со счётчиком.
9. Pending-попапы: `popup_shown=False` попадают в `_init_messaging`; после
   `streams_notify_popup_shown` — не попадают.
10. Изоляция от потоков: отправка уведомления по записи **не** создаёт
    `mail.message`, **не** создаёт и не оживляет канал записи, не меняет его
    unread.
11. Получатель-share (портальный) отбрасывается с `ValidationError`.
12. Транскрипция: с мок-`requests.post` — `transcript`/`done` и отправленный
    `streams.notify/update`; 400 → `failed`; пустой ключ → задание не ставится и
    состояние остаётся `none`.
13. Личный канал: создаётся лениво, ровно один на пользователя (повторный вызов
    хелпера не плодит второй), участник — только владелец.

---

## Б. UI

### Б1. Иконка навбара (§11.4)

`static/src/js/notify_systray.js` + `static/src/xml/notify_systray.xml`:

```js
registry.category("systray").add(
    "streams.NotifyMenu", { Component: StreamsNotifyMenu }, { sequence: 50.5 });
```

- Иконка `fa fa-bell`, бейдж `badge badge-pill` при `counter > 0` (разметка —
  по образцу `mail/static/src/components/messaging_menu/messaging_menu.xml:11-15`).
- Данные — из сервиса Б2 (`counter`), первичное значение из
  `_init_messaging.streams_notify.counter`.
- Клик: `rpc('mail.notify', 'streams_notify_open_channel')` →
  `action.doAction('mail.action_discuss', { additionalContext: { active_id: 'mail.channel_' + id } })`
  (`mail/static/src/widgets/discuss/discuss.js:38-40` читает `active_id` из
  контекста действия). Дропдаун не делаем — §11.4 требует переход в канал.

### Б2. Сервис уведомлений и стек попапов (§12.4)

`static/src/js/notify_service.js` — скелет копирует
`web/static/src/core/notifications/notification_service.js:26-73`:

```js
export const streamsNotifyService = {
    dependencies: ["action", "rpc"],
    start(env, { action, rpc }) {
        const bus = new owl.core.EventBus();
        const state = { counter: 0, popups: [] };
        registry.category("main_components").add(
            "StreamsNotifyContainer",
            { Component: StreamsNotifyContainer, props: { bus, state } });
        // подписка на шину — в env.bus.on("WEB_CLIENT_READY"), как в
        // jkl_develop/static/src/force_reload/force_reload_service.js:10-13
        ...
        return { push, close, markRead, getCounter, openComposer };
    },
};
registry.category("services").add("streams_notify", streamsNotifyService);
```

- Подписка: `bus_service.addChannel('bus_actions_' + uid)` (идемпотентно —
  bus_actions уже добавил, `bus_actions.js:16-20`), `onNotification`,
  `startPolling`; фильтр по трём нашим типам; отписка при destroy.
- Стартовый разбор `_init_messaging.streams_notify.pending` — через патч
  `mail.messaging_initializer._init(data)` (в streams уже есть патч этого
  класса, `static/src/models/messaging_initializer.js:8-25`): читаем ключ и
  зовём `services.streams_notify.push(...)` для каждого элемента.

Контейнер `StreamsNotifyContainer` (правый нижний угол, `z-index` выше
диалогов, стили в `static/src/scss/streams.scss`):
- **не-sticky** — колонка карточек, каждая гасит себя `browser.setTimeout` через
  `popup.timeout * 1000`; наведение мыши таймер приостанавливает;
- **sticky** — одна карточка внизу колонки с пагинатором `‹ 2 / 5 ›` и крестиком,
  закрывающим только текущую (§12.4 «стек с переключением»);
- содержимое карточки: автор + время, ссылка на запись (`record_name`, клик →
  `action.doAction` act_window form), текст, список вложений, `<audio controls>`
  для голоса, транскрипт под плеером (появляется по `streams.notify/update` без
  перерисовки всего стека), кнопка **Reply**;
- закрытие любой карточки шлёт `streams_notify_popup_shown([id])` (батчем,
  дебаунс 500 мс); показ отмечается сразу после первого рендера.

### Б3. Звук (§12.4 «звук на все уведомления») + тумблер Mute

- Проигрываем через messaging-модель `mail.sound_effect`
  (`sound_effect.js:19-34`), файл `dm_02` — свободный слот `soundEffects.newMessage`
  (`sound_effects.js:29-32`), в 15 ядром не используется.
- Играем **только в мастер-вкладке** (`bus_service.isMasterTab()`,
  `bus_service.js:69`) — иначе три открытые вкладки дадут тройной звон.
- Fallback, если messaging ещё не поднят: `new Audio('/mail/static/src/audio/ting.ogg')`,
  как это делает `bus_service._beep()` (`:110-119`).
- **Персональный Mute (решение пользователя):** boolean
  `is_streams_notify_sound_muted` на `res.users.settings` (default False) —
  поле само попадёт в `_init_messaging` через
  `_res_users_settings_format`, паттерн уже использован в 1b
  (`models/res_users_settings.py`). UI-переключатель — кнопка-иконка
  динамика в шапке ленты канала Notifications (Б7), пишет через
  `res.users.settings.set_res_users_settings`; сервис Б2 проверяет флаг перед
  `play()`. Попапы и счётчики от mute не зависят — глушится только звук.
  Тест: при включённом mute `play` не вызывается (юнит на сервисную логику
  или серверный тест на сохранение настройки).

### Б4. Форма отправки (§12.2)

Диалог `StreamsNotifyComposer`, открывается через wowl-сервис `dialog`
(`web/static/src/core/dialog/dialog_service.js:32`):

- **Recipients** — множественный выбор внутренних пользователей
  (`name_search` по `res.users` с доменом `[('share','=',False),('active','=',True)]`);
- **Message** — textarea;
- **Attach files** — `<input type="file" multiple>` → `/mail/attachment/upload`
  (FormData как в `file_uploader.js:71-79`);
- **Record voice** — кнопка записи (Б5), под ней плеер записанного и «Remove»;
- **Sticky** — чекбокс; при включении поле Timeout скрывается и вместо него
  подсказка «The popup stays until the recipient closes it» (§12.2);
- **Timeout (seconds)** — число, дефолт из настроек;
- при наличии записанного голоса Sticky включается принудительно и блокируется
  с подсказкой «Voice notifications are always sticky».

Заголовок и кнопки: `Notify` / `Send` / `Discard` (все строки английские).

### Б5. Запись голоса (§12.3)

`static/src/js/voice_recorder.js`:

- `navigator.mediaDevices.getUserMedia({ audio: true })` (образец обработки
  отказа — `mail/static/src/models/media_preview/media_preview.js:73-90`);
- `MediaRecorder` с первым поддерживаемым mimetype:
  `audio/webm;codecs=opus` → `audio/ogg;codecs=opus` → `audio/mp4` →
  без опций; при отсутствии `MediaRecorder` кнопка записи не рисуется вовсе;
- таймер записи в UI, жёсткий стоп на 5 минутах;
- по `stop` — `new Blob(chunks, {type: mimeType})`, `formData.append('ufile',
  blob, 'voice-YYYYMMDD-HHMMSS.<ext>')` → `/mail/attachment/upload`
  (`thread_model='mail.notify'`, `thread_id=0`, `is_pending=true`);
- трек микрофона обязательно останавливается (`track.stop()`) и при отправке, и
  при закрытии диалога — иначе в браузере остаётся гореть индикатор записи;
- запись доступна **только** в этом диалоге (§12.3) — в чаттер и канал записи
  рекордер не выносим.

### Б6. Кнопка Notify (§11.1, §11.2)

- Чаттер: `static/src/xml/chatter_topbar.xml`, xpath `position="after"` от
  `o_ChatterTopbar_buttonStreamsSendMessage`, кнопка `Notify`; обработчик —
  `registerInstancePatchModel('mail.chatter')` + bind в `_created`, как в
  `static/src/models/chatter.js:11-15`. Открывает диалог Б4 с
  `res_model`/`res_id` треда.
- Канал записи: кнопка `Notify` в шапке треда — тот же файл, что и тумблеры
  фильтров (`static/src/xml/thread_view_topbar.xml`), рядом с ними; параметры
  берутся из `thread.streamsResModel`/`streamsResId`.
- Канал Notifications: кнопка `New notification` в шапке ленты (Б7) — без
  привязки к записи.

### Б7. Лента канала Notifications (§12.5)

Компонент `StreamsNotifyFeed` подменяет ThreadView, когда
`thread.streamsChannelKind === 'notifications'` (общий с фазой 2 xpath по
`mail.Discuss`, `t-if` по kind — см. блок координации):

- две вкладки **Received** / **Sent**, данные из `streams_notify_feed(box)`,
  подгрузка вниз по `before_id`;
- карточка Received: автор, время, текст, вложения, плеер + транскрипт, кнопка
  **Reply**; непрочитанные визуально выделены;
- карточка Sent: текст и по строке на получателя — `Read at 14:32` либо
  `Unread`;
- клик по `record_name` открывает запись (`action.doAction` act_window form);
- прочитанность: `IntersectionObserver` на карточках Received, порог 0.9,
  дебаунс 500 мс → `streams_notify_mark_read(ids)`; бейдж навбара и счётчик
  канала обновляются по `streams.notify/counter`;
- новые уведомления приезжают по `streams.notify/new` и вставляются наверх без
  перезагрузки фида.

Маршрутизация в сайдбаре: `_getDiscussSidebarCategory` уже пропускает через
super всё, кроме `record` (`static/src/models/thread.js:61-66`), поэтому личный
канал попадает в ядровую категорию Channels. Отдельной категории для него не
заводим (один канал — не повод), но пункт держим первым: `sortComputeMethod`
трогать не нужно, достаточно того, что доступ к нему основной — через иконку
навбара.

### Б8. Что НЕ делать

- Не патчить `mail/static/src/models/attachment/attachment.js` (`isVideo`/
  `isViewable`) — плеер рисуем свой.
- Не заводить свой bus-канал и свой JS-сервис подписки поверх `bus_actions`.
- Не использовать `notification`-сервис для попапов уведомлений (тосты —
  только для служебных сообщений об ошибках формы).
- Не добавлять рекордер в чаттер/канал записи/гостевую страницу.
- Не трогать ядровый `message_notify` и `user_notification` — уведомления
  живут вне `mail.message`.
- `@mention` в теле уведомления, шаблоны и отложенная отправка — вне фазы.

---

## В. Браузерный прогон (обязателен)

Среда — из контекста ветки (`worried-horse`). Скриншоты фоновой вкладки на
этой машине не рисуются: проверять по DOM через `evaluate_script`. При 429 у
browser-rendering — `mcp__paseo__browser_*`.

1. Логин; иконка-колокол в навбаре есть и стоит **слева вплотную** к иконке
   Discuss; бейджа нет.
2. Карточка партнёра → кнопка **Notify** → диалог: выбрать себя вторым
   получателем, текст, timeout 5, Send. Попап появился, автоматически исчез
   примерно через 5 с; бейдж стал 1.
3. Отправить два **sticky**: обе карточки не гаснут, пагинатор показывает
   `1 / 2`, крестик закрывает по одной.
4. Голос: подтвердить, что кнопка записи есть и при отказе в микрофоне даёт
   английское сообщение об ошибке (микрофона в headless нет — саму запись
   проверяем вручную). Плеер и транскрипт проверить на уведомлении, созданном
   через `run_odoo_shell` с готовым аудио-вложением: в DOM попапа есть
   `<audio controls>`.
5. Discuss → канал **Notifications**: вкладка Received содержит отправленные
   уведомления; после скролла бейдж и счётчик канала обнулились; вкладка Sent
   показывает `Read at ...`.
6. Reply из карточки: ответ пришёл автору исходного, sticky унаследован.
7. Консоль без ошибок `streams`.

---

## Процесс

Как в фазах 1a/1b/2: правка → commit/push (`Co-Authored-By: Claude Fable 5
<noreply@anthropic.com>`) → сразу `pull_and_apply(env_name="worried-horse",
upgrade="streams")` (новые модели, данные, ассеты — только `-u`, не restart) →
читать ошибки прямо в ответе → `run_odoo_tests(modules="streams")` (все прежние
сценарии + новые зелёные). Версия — 15.0.1.3.0.

Дополнительно для этой фазы:
- перед проверкой транскрипции убедиться, что в `/etc/odoo/odoo.conf` среды есть
  `server_wide_modules = web,queue_job`, и в логах поднялся jobrunner
  (корневой `AGENTS.md:249-258`); без этого задание повиснет в `pending` и
  подберёт его только крон;
- ключ `openai_api_key` в тестовой среде, скорее всего, пуст — проверить обе
  ветки: без ключа `transcript_state` остаётся `none`, с ключом (если его
  выдадут) — `done`;
- известный шум прод-шаблона про `mcp_server` — игнорировать.

По завершении обновить `roadmap.md`: секция «Сделано» (Фаза 3), отступления от
ТЗ и раздел «To check / to do» (в частности пункт про
`supply_wagon_tracking._notify_followers` — теперь его заменяет Notify).
