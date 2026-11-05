# Дизайн фазы 6 — streams_mobile: серверный API мобильного клиента

Дата: 2026-08-18. Исходное ТЗ —
https://gist.github.com/Buburuzac/56eb12c32e0f0fc251f010065409c928
(написано под Odoo 15; этот документ — его адаптация к Odoo 19 и
портированному `streams` фазы 5). Клиент — Flutter (решение пользователя),
живёт в `app/` этого репозитория (фаза 7).

## 1. Объём фазы 6 (сервер)

Новый модуль **`addons/streams_mobile`**, `depends = ['streams']`.
Версионированные маршруты `/streams/mobile/v1/...`. В фазу входят:

1. Токен-аутентификация: модель `streams.mobile.device`, login/logout,
   регистрация push-токена.
2. API v1: init, список каналов, лента канала с фильтрами потоков,
   отправка comment/note, отметки прочтения, персистентные фильтры,
   лента Changes, Notify (лента/отправка/ответ/прочтение/popup),
   подписка на поля, вложения (upload/download), poll-эндпоинт
   (замена longpolling из ТЗ — в 19 его нет).
3. Push-инфраструктура: очередь через `queue_job`, политика по потокам,
   транспорт FCM **заглушкой** (лог + запись в модель очереди) до
   появления ключей Firebase (решение: ключей пока нет).
4. Тесты: аутентификация (выдача/отзыв/инвалидация при смене пароля),
   ACL пушей, политика по потокам, контракты эндпоинтов.

Вне фазы: голосовая запись на клиенте (модель уже поддерживает вложения),
websocket-транспорт (poll в v1), Telegram, гостевой мобильный доступ.

## 2. Аутентификация

### 2.1. Модель `streams.mobile.device`

| Поле | Тип | Назначение |
|---|---|---|
| `user_id` | m2o res.users, required, index, ondelete=cascade | владелец |
| `name` | char | имя устройства («Pixel 9 Pro») |
| `platform` | selection ios/android/other | |
| `app_version` | char | |
| `token_hash` | char, index, groups=base.group_system | sha256 секрета |
| `push_token` | char, groups=base.group_system | FCM registration token |
| `push_enabled` | boolean, default True | |
| `last_activity` | datetime | обновляется не чаще раза в 5 минут |
| `active` | boolean | отзыв устройства |

- Секрет: `secrets.token_urlsafe(32)`; клиенту выдаётся
  `"<device_id>|<secret>"`, в БД — только sha256. Сверка — `hmac.compare_digest`.
- **Инвалидация при смене пароля**: override `res.users.write` в
  streams_mobile — смена `password` архивирует все устройства пользователя.
- Отзыв: пользователь видит свои устройства (ir.rule «только свои»),
  админ — все; `action_revoke` (`active=False`).
- ACL: пользователю r/w только свои устройства; create — только через
  login-контроллер (sudo внутри, после проверки пароля).

### 2.2. Маршруты

Все — `type='jsonrpc'`, POST (клиент шлёт стандартный JSON-RPC 2.0
конверт, как требует ТЗ). Публичные (`auth='none'`) — только login;
остальные `auth='public'` + собственная проверка Bearer.

- `POST /streams/mobile/v1/auth/login`
  `{login, password, totp_code?, device_name, platform, app_version}` →
  `{token, device_id, user: {id, name, partner_id}, server_version}`.
  Проверка пароля — штатным `res.users` credential-API 19 (без sudo-обхода);
  TOTP: если у пользователя включён 2FA и `totp_code` не передан/неверен —
  ошибка `totp_required`/`totp_invalid`.
- `POST /streams/mobile/v1/auth/logout` — архивирует устройство.
- `POST /streams/mobile/v1/push/register` `{push_token, push_enabled}`.

### 2.3. Авторизация запросов

Заголовок `Authorization: Bearer <device_id>|<secret>`. Хелпер
`_streams_mobile_env(request)`:

1. достаёт устройство sudo-поиском по id, сверяет hash, `active`,
   активность пользователя;
2. `request.update_env(user=device.user_id)` — **дальше всё выполняется
   правами пользователя, без sudo** (инвариант ТЗ);
3. троттлит `last_activity`.

Ошибки — JSON `{error: {code, message}}`: `auth_failed` (401-семантика),
`access_denied`, `not_found`, `bad_request`.

## 3. API v1 (эндпоинты и форматы)

Формат ответов — компактный собственный JSON (не Store): мобильному
клиенту не нужен реляционный протокол веб-клиента, а контракт фиксируется
тестами. Даты — UTC ISO 8601. Пагинация — `before_id`/`limit`.

- `POST /v1/init` → `{user, notify: {counter, channel_id, default_timeout,
  pending_popups[]}, unread_total, filters_defaults, server_time}`.
- `POST /v1/channels` `{kinds?, search?, limit?, offset?}` → секции ТЗ:
  `{channels: [{id, name, kind (record/changes/notifications/chat/channel/
  group), res_model, res_id, unread, last_message: {...} | null,
  members_count}]}` — record-каналы, личные Changes/Notifications, обычные
  каналы и DM текущего пользователя (членство).
- `POST /v1/channel/messages` `{channel_id, before_id?, limit?}` →
  `{messages: [{id, body, date, kind, author: {id, name}, attachments:
  [{id, name, mimetype, size}], tracking: [{field, label, old, new}]|null,
  reactions: [{content, count, me}], parent_id}]}` — домен ленты =
  проекции (`_streams_message_domain`), tracking-значения отдаются только
  для change-сообщений и только по правам; для личного канала Changes —
  собственный формат `streams_changes_feed`.
- `POST /v1/channel/post` `{channel_id, body, kind: comment|note,
  attachment_ids?, mentioned_partner_ids?}` → сообщение (формат выше).
  Для record-канала пост идёт через reverse-post механику streams (право
  чтения записи проверяет сервер).
- `POST /v1/channel/mark_read` `{channel_id, last_message_id}` →
  `member._mark_as_read` (форк с проекциями).
- `POST /v1/channel/filters` `{channel_id, filters?}` → get/set
  персистентных фильтров потоков (§6 roadmap).
- `POST /v1/changes/feed` `{before_id?, limit?}` →
  `streams_changes_feed` as-is.
- `POST /v1/fields/subscription` `{res_model, res_id, field_ids?}` →
  get/set (`streams_get/set_field_subscription`).
- `POST /v1/notify/feed` `{box: received|sent, before_id?, limit?}`,
  `POST /v1/notify/send` `{body, user_ids, attachment_ids?, is_sticky?,
  timeout?, res_model?, res_id?}`, `/v1/notify/reply`,
  `/v1/notify/mark_read`, `/v1/notify/popup_shown` — обёртки над RPC
  фазы 3 (`streams_notify_*`), контракты не дублируются.
- `POST /v1/poll` `{last_bus_id}` → `{last_bus_id, notifications:
  [{id, type, payload}]}` — выборка `bus.bus` по каналу партнёра
  пользователя (и только его) с `id > last_bus_id`; замена
  longpolling-прокси из ТЗ (в 19 `/longpolling/poll` не существует,
  websocket — кандидат v2). Типы совпадают с веб-шиной:
  `discuss.channel/new_message`, `streams.notify/*`,
  `streams.changes/updated`, `mail.record/insert`.
- `POST (http) /v1/attachment/upload` (multipart, csrf=False) — pending
  (`res_model='mail.compose.message'`, `res_id=0`), лимиты как у гостя;
  `GET /v1/attachment/<id>` — выдача через `ir.binary` с проверкой прав
  пользователя на сообщение/уведомление-владельца.

## 4. Пуши (политика §ТЗ, транспорт-заглушка)

- Точки входа: `mail.notify._streams_broadcast_new` (notify — всегда всем
  получателям) и `mail.thread._streams_broadcast` (проекции: comment /
  message — участникам канала кроме автора; note — только явно
  упомянутым, `partner_ids` сообщения; change/activity — никогда).
  Получатель без права чтения записи не получает тело (переиспользуется
  `_streams_readable_partners`) — в push тогда не идёт ничего.
- Модель-очередь `streams.mobile.push` (device, title, body, data JSON,
  state queued/sent/failed/skipped) + `with_delay()` (queue_job, канал
  `root.streams_mobile`, ретраи как у транскрипции) + cron-страховка.
- Транспорт `_streams_mobile_send_push(device, payload)`: если в
  `ir.config_parameter` есть `streams_mobile.fcm_service_account_json` —
  FCM HTTP v1; иначе state='skipped' + debug-лог. Мёртвый FCM-токен
  (`UNREGISTERED`) деактивирует устройство.
- Payload ≤ 4KB, тело обрезается; deep link `{model, res_id, channel_id}`.

## 5. Структура модуля

```
addons/streams_mobile/
  __manifest__.py          # depends: streams; без ассетов
  models/streams_mobile_device.py
  models/streams_mobile_push.py
  models/mail_notify.py    # хук пушей notify
  models/mail_thread.py    # хук пушей проекций
  models/res_users.py      # инвалидация токенов при смене пароля
  controllers/auth.py      # login/logout/push register
  controllers/api.py       # v1 эндпоинты
  security/                # ACL + ir.rule «свои устройства/пуши»
  data/streams_mobile_data.xml  # cron страховки пушей, queue.job.function
  views/streams_mobile_device_views.xml  # список устройств (админ)
  tests/test_mobile_auth.py, test_mobile_api.py, test_mobile_push.py
  docs/api-v1.md           # контракт API для клиента (генерируемый вручную)
```

## 6. Критерии готовности фазы

`run_odoo_tests(modules="streams_mobile")` зелёный; `streams` остаётся
зелёным; ручная проверка login → init → channels → post → poll через
`http_request_to_odoo` в окружении streams19.

## 7. Фаза 7 (клиент, отдельный док по факту)

Flutter-приложение в `app/`: экраны Login, Channels (секции +
поиск по имени), Channel (лента с фильтрами потоков, композер
Comment/Note, вложения), Changes, Notify (лента + попапы + отправка),
Settings. Обновления: poll каждые N секунд в foreground; FCM — после
появления ключей. Локализация en/pl/ru/uk — каркас сразу (ARB).
