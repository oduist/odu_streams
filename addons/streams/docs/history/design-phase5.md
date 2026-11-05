# Дизайн фазы 5 — порт модуля streams на Odoo 19

Дата: 2026-08-18. Решение пользователя: целевая платформа проекта меняется с
Odoo 15 на **Odoo 19.0**; далее на портированном ядре строится
`streams_mobile` (серверный API + мобильное приложение на Flutter).

Исходное состояние: `streams` 15.0.1.4.0, фазы 1–4 реализованы, 70 зелёных
тестов. Baseline-коммит Odoo-15 версии — `c35ae57`. Окружение для порта —
Oduflow `streams19` (odoo:19.0, live-mount репозитория,
addons_path=/mnt/extra-addons/addons, extra-addons: OCA queue 19.0).

Все file:line ядра 19 ниже — из контейнера окружения (образ odoo:19.0,
сборка 2026-08-17), корень `/usr/lib/python3/dist-packages/odoo/addons`
(далее `<core>`).

---

## 1. Объём фазы

**Входит (Stage A, эта фаза):**

1. Порт всего серверного ядра: модели, wizard'ы, контроллеры, data/security,
   hooks, манифест.
2. Порт гостевой подсистемы целиком (модель + контроллеры + публичная
   страница): она самодостаточна (vanilla JS без ассетов Odoo) и переносится
   с точечными правками.
3. Порт всех 70 тестов, зелёный прогон `run_odoo_tests(modules="streams")`.

**Не входит (фиксируется здесь, делается отдельными фазами):**

- **Веб-UI бэкенда** (патчи Discuss/чаттера, фильтры потоков, Notify-попапы,
  лента Changes, systray): фреймворк messaging-моделей 15
  (`@mail/model/model_core`) в 19 не существует, весь слой `static/src/`
  (кроме `static/src/guest/`) переписывается с нуля под OWL 2 + Store.
  Это отдельная фаза после `streams_mobile` (решение по очерёдности —
  за пользователем; мобильный клиент от веб-UI не зависит).
  В Stage A ассеты из манифеста убираются, легаси-JS перемещается в
  `static/legacy15/` как референс.
- **Миграция данных 15 → 19** (перенос живой базы VelesAgro): отдельная
  задача со своими migrate-скриптами (переименование таблиц
  `mail_channel*` → `discuss_channel*`, перенос rel-таблицы, §15 roadmap).
  Порт делается для чистой установки на 19.
- Переход гостевой страницы с AJAX-поллинга на websocket — сознательно нет
  (архитектура §9.5 roadmap сохраняется).

---

## 2. Карта фактов ядра Odoo 19

### 2.1. Каналы

- `discuss.channel` — `<core>/mail/models/discuss/discuss_channel.py:49`,
  `_inherit = ["mail.thread", "bus.listener.mixin"]`.
- `channel_type` — Selection `chat/channel/group`, required, **readonly**,
  `write()` запрещает смену (`:437`). Поэтому наш вид канала остаётся
  отдельным полем `channel_kind` (record/changes/notifications) при
  `channel_type='channel'` — как в 15.
- Участник — `discuss.channel.member`
  (`<core>/mail/models/discuss/discuss_channel_member.py:22`);
  `channel_member_ids` (`discuss_channel.py:84`), computed
  `channel_partner_ids` (`:80`).
- `create()` каналов (`:375`) валидирует команды o2m/m2m и whitelist полей
  члена `_get_allowed_channel_member_create_params()` (`:371`); контекст
  `mail_create_nolog/nosubscribe` ставится сам (`:418`).
- Члены: `add_members()` (`:595`) — обёртка над `_add_members(*, partners,
  users, guests, ...)` (`:606`, keyword-only), постит «joined» и шлёт Store.
  Выход — `_action_unfollow(partner, guest, post_leave_message)` (`:561`).
- `_message_subscribe` на канале кидает UserError (`:1069`) — followers у
  самого канала запрещены. Наша синхронизация «члены канала ⇄ followers
  записи-источника» под запрет не попадает (followers живут на записи).
- Точки расширения по типам: `_types_allowing_seen_infos` (`:1414`),
  `_types_allowing_unfollow` (`:1419`), `_lazy_load_members_channel_types`
  (`:1430`).

### 2.2. Сообщения и проекции

- **M2M message↔channels в ядре нет** (удалён в 16). Сообщение принадлежит
  каналу только через `model='discuss.channel'` + `res_id`; computed
  `channel_id` — `<core>/mail/models/discuss/mail_message.py:11`.
- Unread члена — `new_message_separator` (Integer,
  `discuss_channel_member.py:38`), `_compute_message_unread` — сырой SQL по
  `model='discuss.channel' AND res_id=channel_id`, исключает
  `message_type IN ('notification','user_notification')` (`:153-173`).
- Прочтение: `/discuss/channel/mark_as_read`
  (`<core>/mail/controllers/discuss/channel.py:112`) →
  `member._mark_as_read(last_message_id)` (`discuss_channel_member.py:614`)
  → `_set_last_seen_message` (`:633`) + `_set_new_message_separator` (`:662`).
- `seen_message_id`/`fetched_message_id` остались (`:36-37`), но только для
  галочек seen info (chat/group).

### 2.3. Pipeline message_post

- `message_post` — **все параметры keyword-only**
  (`<core>/mail/models/mail_thread.py:2195`).
- Кастомные поля сообщения режутся whitelist'ом
  `_get_message_create_valid_field_names()` (`:3068`); нестандартные
  notify-kwargs — `_get_notify_valid_parameters()` (`:3300`).
- Порядок: `_message_create` → подписка автора (контексты
  `mail_post_autofollow`, `mail_post_autofollow_author_skip`, `:2305-2366`)
  → `_message_post_after_hook(new_message, msg_values)` (`:2368`) →
  `_notify_thread` (`:3275`).
- Нотификаторы: `_notify_thread_by_inbox` (`:3336`),
  `_notify_thread_by_email` (`:3390`), `_notify_thread_by_web_push`
  (`:3891`). Метода `_notify_record_by_email` из 15 нет.
- `discuss.channel.message_post` сам ставит `mail_post_autofollow=False,
  mail_post_autofollow_author_skip=True` (`discuss_channel.py:1006-1024`).
- `message_type` расширен: `email_outgoing`, `auto_comment`,
  `out_of_office` (`mail_message.py:119-137`).

### 2.4. Tracking

- Precommit-механика: `_track_prepare` (`mail_thread.py:526`) →
  `_track_finalize` (`:566`) → `_message_track(fnames, initial_values)`
  (`:645`): если `_track_subtype` (`:632`) вернул подтип — `message_post`
  с `message_type='notification'`, иначе `_message_log`.
- `tracking_value_ids` — теперь `groups="base.group_system"`
  (`mail_message.py:180-186`); чтение для клиента — только
  `_tracking_value_format` (`mail_tracking_value.py:197`).
- Tracking-сообщения ядро само исключает из unread и из рассылки канала
  (`discuss_channel_member.py:158-165`, `discuss_channel.py:824-827`).

### 2.5. Bus / websocket

- `bus.bus._sendone(target, type, payload)` (`<core>/bus/models/bus.py:110`):
  target — recordset (user/partner/канал), `(record, subchannel)` или str.
  **`_sendmany` удалён.** Рекомендованный путь —
  `bus.listener.mixin._bus_send(type, message, subchannel=None)`
  (`bus_listener_mixin.py:15`); его наследуют channel/member/message/guest/
  users/partner.
- Longpolling мёртв: `/websocket` (`bus/controllers/websocket.py:11`),
  fallback `/websocket/peek_notifications` (`:31`). Кастомные строковые
  каналы клиента резолвятся в override `_build_bus_channel_list`
  (`bus/models/ir_websocket.py:15`, пример discuss —
  `mail/models/discuss/ir_websocket.py:14-38`).

### 2.6. Store (протокол клиента)

- `Store` — `<core>/mail/tools/discuss.py:82`: `add()`, `add_global_values()`,
  `get_result()`, `bus_send(type="mail.record/insert")`; дескрипторы
  `Store.Attr/One/Many`.
- Модели реализуют `_to_store_defaults(target)` / `_to_store(store, fields)`:
  канал — `discuss_channel.py:1218/1313`, сообщение —
  `mail_message.py:1096/1158`, член — `discuss_channel_member.py:389`.
- Роуты `/mail/action`, `/mail/data` (`mail/controllers/webclient.py:14/22`),
  init-данные — `res.users._init_messaging(store)`
  (`mail/models/res_users.py:434`, discuss: `discuss/res_users.py:45`).
- `channel_info()` / `message_format()` / `_message_format()` из 15 не
  существуют.

### 2.7. Прочее

- `mail.guest` — нативная гостевая подсистема (`mail_guest.py:16`, cookie
  `dgid`, `add_guest_to_context`). Для наших требований (одноразовая ссылка,
  POST-подтверждение, `history_from`, окно правки, ротация в дайджесте,
  гость ≠ участник канала) не подходит: приглашение по `channel.uuid` —
  постоянная ссылка, гость становится членом канала (утёк бы в зеркало
  followers §5.3). Свой `mail.channel.external.participant` сохраняется,
  переименовывается только ссылка на модель канала.
- Web Push ядра (`mail.push.device`, `_notify_thread_by_web_push`,
  `mail_thread.py:3891`) — транспорт VAPID для браузеров; для FCM в
  `streams_mobile` переиспользуем паттерн (модель устройств + очередь +
  хуки выбора получателей), но транспорт свой.
- ORM/API: `invalidate_cache`/`flush` удалены (→ `env.invalidate_all`,
  `flush_model`, `flush_recordset`); `name_get` удалён (→ `display_name`);
  `check_access_rights/rule` → `check_access(operation)`;
  `_update_content` → `_message_update_content`; `_get_content_common` →
  сервис `ir.binary`; `attrs=` во вьюхах удалён; `type='json'` в роутах →
  `type='jsonrpc'`; бандл `web.assets_qweb` не существует;
  `@api.model_create_multi` — единственный вид override create;
  `_sql_constraints` → декларативные `models.Constraint`/`models.UniqueIndex`
  (старый синтаксис пока работает, использовать новый);
  post_init_hook получает `env`, а не `(cr, registry)`.

---

## 3. Архитектурные решения порта

1. **Проекции сохраняются как в 15**: собственная m2m
   `mail.message.stream_channel_ids` (rel `mail_message_stream_channel_rel`)
   на `discuss.channel`. Следствие — форки в новых местах ядра:
   - лента канала: домен «свои сообщения ∪ проекции» — в
     `discuss.channel._message_fetch`-цепочке (в 15 это был контроллер
     `/mail/channel/messages`; в 19 точка определяется по факту —
     контроллер `/discuss/channel/messages` или модельный метод);
   - unread: форк `discuss.channel.member._compute_message_unread`
     с ветками record/changes/notifications (перенос
     `_streams_compute_*_unread` с `mail.channel` на member) и правилами
     потоков §7 (comment/message считаются, note — только упоминания,
     change/activity — никогда);
   - `_mark_as_read`/`_set_last_seen_message` — досчёт наших веток.
2. **Виды каналов**: `channel_kind`, `res_model`, `res_id`, `owner_user_id`,
   `company_id` — без изменений; `channel_type='channel'`,
   `group_public_id=False`. Частичные UNIQUE-индексы переезжают на новый
   декларативный синтаксис (`models.UniqueIndex`).
3. **Синхронизация участники ⇄ followers записи** сохраняется: overrides
   `create`/`unlink` переезжают с `mail.channel.partner` на
   `discuss.channel.member`, guard-контекст `streams_sync` без изменений.
   Добавление членов ядровым путём — через `_add_members` (новая сигнатура).
4. **Классификатор потоков и подтипы** — без изменений (data XML тот же).
   Служебные «joined/left» ядра в каналах записей гасятся как в 15
   (override `_add_members`/`_action_unfollow` с `post_joined_message=False`
   / `post_leave_message=False`).
5. **Change-сообщения**: `mail_extra_recipients` больше нет; его роль
   (весь tracking — log-only) забирает сам streams: override
   `_message_track` направляет создание в `_message_log`; существующий
   override `_message_log` (подтип `streams.mt_change`) сохраняется.
   Форк «change не трогает unread» ядру больше не нужен — ядро само не
   считает `notification`-сообщения; наши ветки unread это учитывают.
6. **Рассылка**: email внутренним запрещаем в `_notify_thread_by_email`
   (замена `_notify_record_by_email`); адресная bus-доставка проекций —
   `Store(bus_channel=partner).add(message).bus_send(...)` /
   `partner._bus_send(...)` циклом (замена `_sendmany`), ACL-проверка
   `_streams_readable_partners` сохраняется.
7. **Notify**: `bus_actions` заменяется на `user.partner_id._bus_send
   ('streams.notify/new'|'/update', payload)`. Payload пока свой
   (JSON фазы 3) — потребители появятся в фазах UI-порта и streams_mobile.
   `queue_job` остаётся (OCA 19.0), `data/streams_notify_data.xml` совместим.
8. **Клиентские форматы**: `channel_info()` → `_to_store_defaults` на
   `discuss.channel` (ключи `channel_kind`, `res_model`, `res_id`,
   `streams_filters`); `_message_format` → `_to_store` на `mail.message`
   (`streams_kind`, `stream_channel_ids`); `_init_messaging` →
   `res.users._init_messaging(store)` + `store.add_global_values
   (streams_notify=...)`.
9. **Фильтры потоков** — `streams_filters` (JSON) переезжает на
   `discuss.channel.member`; RPC `streams_set_filters` сохраняется.
10. **Гостевая подсистема** — порт as-is: `type='jsonrpc'`, `ir.binary`
    вместо `_get_content_common`, `_message_update_content`,
    `message_post(**kw)` keyword-only, `attrs=` из вьюх, `_add_members`.
11. **Манифест**: `depends = ['mail', 'queue_job']`; `mailgun`,
    `mail_extra_recipients`, `bus_actions` удаляются (обоснование —
    отчёт по зависимостям, 2026-08-18: mailgun — ноль использований,
    bus_actions — 4 call-site → `_bus_send`, mail_extra_recipients —
    только семантика log-only tracking, поглощается п.5). Версия —
    `19.0.1.4.0` (паритет функциональности с 15.0.1.4.0).

## 4. Состав работ по файлам

| Файл 15 | Файл 19 | Ключевые изменения |
|---|---|---|
| `models/mail_channel.py` | `models/discuss_channel.py` | `_inherit='discuss.channel'`; SQL по `discuss_channel`; `channel_info`→`_to_store_defaults`; форки fetch/seen/unread переезжают (unread → member); `name_get`→`display_name`; `flush`/`invalidate_cache`→новый API; `add_members`→`_add_members` |
| `models/mail_channel_partner.py` | `models/discuss_channel_member.py` | `_inherit='discuss.channel.member'`; зеркало followers; `streams_filters`; ветки `_compute_message_unread` |
| `models/mail_message.py` | = | m2m на `discuss.channel`; `_message_format`→`_to_store`; классификатор без изменений; SQL-линковка — те же таблицы |
| `models/mail_thread.py` | = | `_message_auto_subscribe*` no-op (сигнатуры 19); `_notify_record_by_email`→`_notify_thread_by_email`; `message_post` kw-only; `+_message_track` override (log-only); `_streams_broadcast` → Store/_bus_send; `check_access` |
| `models/mail_notify.py` | = | `bus.actions.signal`→`partner._bus_send`; `channel_info()[0]`→Store-словарь; остальное совместимо |
| `models/mail_channel_external_participant.py` | = | ссылки на `discuss.channel`; `_update_content`→`_message_update_content`; bus `mail.message/insert`→свой тип для гостевой страницы (страница своя, формат наш); `channel_partner_ids`→`channel_member_ids.partner_id` |
| `models/mail_field_subscription.py` | = | почти без изменений (`_sql_constraints`→`models.Constraint`) |
| `models/mail_activity.py` | = | проверка `_action_done` против 19 (`action_feedback` совместим) |
| `models/res_users.py` | = | `_init_messaging(store)` — новая сигнатура |
| `models/res_users_settings.py` | = | модель теперь в base — `_inherit` тот же |
| `models/res_config_settings.py` | = | без изменений |
| `models/mail_compose_message.py`, `mail_wizard_invite.py` | = | сверка полей/доменов с 19 |
| `controllers/discuss.py` | = | точка форка домена ленты — по факту API 19 (`/discuss/channel/messages`) |
| `controllers/guest.py` | = | `type='jsonrpc'`; `ir.binary`; остальное as-is |
| `wizard/*` | = | `attrs=`→выражения; логика без изменений |
| `hooks.py` | = | сигнатура `post_init_hook(env)` |
| `__manifest__.py` | = | depends/версия/ассеты (см. п.3.11); `web.assets_qweb` удалить |
| `views/*.xml` | = | `attrs=`→`invisible=`/`readonly=`; `<tree>`→`<list>` (если есть) |
| `data/*.xml` | = | без изменений (проверить xml-id ядра) |
| `security/*` | = | без изменений |
| `static/src/*` (кроме guest) | `static/legacy15/` | вынести из ассетов; переписывание — отдельная фаза |
| `static/src/guest/*` | = | as-is (vanilla JS, отдаётся статикой) |
| `tests/*` | = | модельные имена; `_flush_tracking` → precommit 19; парсинг `bus.bus` под новый формат каналов/payload; сигнатуры |

## 5. Порядок работ и критерии готовности

1. Манифест + скелет (модуль ставится на 19 пустым набором override'ов) —
   `pull_and_apply(install="streams")` без ошибок.
2. Модели по порядку зависимости: message → channel/member → thread →
   field_subscription → activity → notify → external_participant →
   res_users/settings/config → wizards → controllers → hooks.
3. Тесты пофайлово: `test_streams` → `test_streams_ui` →
   `test_streams_changes` → `test_streams_notify` → `test_streams_guest`.
4. Критерий готовности фазы: `run_odoo_tests(modules="streams")` — все
   сценарии зелёные на чистой базе 19; установка/удаление/повторная
   установка модуля без ошибок; roadmap обновлён (раздел «Сделано»).

## 6. Риски

1. Форк unread на `discuss.channel.member` — самая тонкая часть: ядровый
   SQL не знает о проекциях, наши ветки должны точно повторить правила §7
   (и не сломать mark_as_read/new_message_separator).
2. Whitelist'ы `_get_message_create_valid_field_names` /
   `_get_notify_valid_parameters` — места, где 15-код молча работал, а
   19 бросит исключение; ловится тестами.
3. Bus-события старого формата, которые незачем эмулировать: потребителей
   веб-UI пока нет; контракт фиксируется под будущий OWL-порт и мобильный
   API (типы `streams.*` + Store для ядровых сущностей).
4. `queue_job` OCA 19.0 в связке с precommit-трекингом — проверить, что
   `with_delay` из precommit-контекста не даёт сюрпризов (тест 12 фазы 3).
