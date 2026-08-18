# Streams Mobile API v1 — контракт для клиента

База: `/streams/mobile/v1`. Все эндпоинты, кроме отмеченных как http,
принимают JSON-RPC 2.0 POST (`Content-Type: application/json`):

```json
{"jsonrpc": "2.0", "method": "call", "id": 1, "params": { ... }}
```

Ответ приходит в `result` конверта. Даты — строки UTC ISO 8601
(`"2026-08-18 12:00:00"`). Пагинация лент — `before_id` (отдать записи
с id меньше) + `limit` (сервер зажимает в 1..100, по умолчанию 30).

## Авторизация

Все эндпоинты, кроме `/auth/login`, требуют заголовок:

```
Authorization: Bearer <device_id>|<secret>
```

Строка токена выдаётся логином один раз и не восстанавливается. Токен
перестаёт работать после `/auth/logout`, отзыва устройства админом или
смены пароля пользователя.

## Формат ошибок

Ошибка — обычный `result` с единственным ключом `error`:

```json
{"error": {"code": "access_denied", "message": "You have no access to this channel"}}
```

Коды: `auth_failed` (нет/протух токен — перелогин), `access_denied`,
`not_found`, `bad_request`, `totp_required`, `totp_invalid`.
Http-эндпоинты вложений дополнительно используют статусы 400/401/404/413.

## Аутентификация

### POST /auth/login

Параметры: `login`, `password`, `totp_code?`, `device_name?`,
`platform?` (`ios|android|other`), `app_version?`.

```json
{
  "token": "42|u_kX...",
  "device_id": 42,
  "user": {"id": 6, "name": "Alice", "partner_id": 9},
  "server_version": "19.0.1.0.0"
}
```

При включённом 2FA без кода — `totp_required`, с неверным — `totp_invalid`.

### POST /auth/logout

Без параметров. Архивирует устройство. → `{"ok": true}`

### POST /push/register

`{push_token, push_enabled}` — FCM-токен устройства. → `{"ok": true}`

## Старт клиента

### POST /init

Без параметров.

```json
{
  "user": {"id": 6, "name": "Alice", "partner_id": 9},
  "notify": {
    "counter": 2,
    "channel_id": 15,
    "default_timeout": 10,
    "pending": [ {"id": 7, "body": "...", "author": {...}, ...} ]
  },
  "unread_total": 5,
  "filters_defaults": {"comment": true, "note": true, "message": true,
                       "change": false, "activity": true},
  "server_time": "2026-08-18 12:00:00"
}
```

`notify` — payload `_streams_init_messaging`: счётчик непрочитанных
уведомлений, id личного канала Notifications (`null`, если ещё не
создан), таймаут попапа и накопившиеся непоказанные попапы (формат
элемента — как в `/notify/feed`). `unread_total` — сумма непрочитанного
по всем каналам пользователя.

## Каналы

### POST /channels

Параметры: `kinds?` (список из `record|changes|notifications|chat|
channel|group`), `search?` (подстрока имени), `limit?`, `offset?`.
Возвращаются только каналы, где пользователь — участник; сортировка по
свежести последнего сообщения.

```json
{"channels": [
  {
    "id": 21,
    "name": "Deco Addict",
    "kind": "record",
    "res_model": "res.partner",
    "res_id": 14,
    "unread": 3,
    "last_message": { ...формат сообщения... },
    "members_count": 4
  }
]}
```

`last_message` может быть `null` (сообщений нет или к записи-источнику
потерян доступ).

### POST /channel/messages

`{channel_id, before_id?, limit?}` → лента канала, свежие первыми.
Доступ: участник канала, либо право чтения записи для record-канала.
Для личного канала Changes — `bad_request` (используйте `/changes/feed`).

Формат сообщения (везде одинаковый):

```json
{"messages": [
  {
    "id": 101,
    "body": "<p>Привет</p>",
    "date": "2026-08-18 11:58:03",
    "kind": "comment",
    "author": {"id": 9, "name": "Alice"},
    "attachments": [
      {"id": 5, "name": "spec.pdf", "mimetype": "application/pdf", "size": 12345}
    ],
    "tracking": null,
    "reactions": [{"content": "👍", "count": 2, "me": true}],
    "parent_id": null
  }
]}
```

`kind`: `comment | note | message | change | activity | false` (прочее).
`tracking` — только у `change`-сообщений и только по правам пользователя
(поля с недоступными группами скрываются): список
`{"field": "email", "label": "Email", "old": "a@x", "new": "b@x"}`.

### POST /channel/post

`{channel_id, body, kind: "comment"|"note", attachment_ids?,
mentioned_partner_ids?}` → отправленное сообщение (формат выше).

`body` — обычный текст, сервер экранирует его сам. `attachment_ids` —
id, полученные из `/attachment/upload` (перепривязываются к сообщению).
Для record-канала сообщение публикуется на запись (reverse-post) —
сервер проверит право чтения записи; без права — `access_denied`.
Личные каналы Changes/Notifications — только чтение (`bad_request`).

### POST /channel/mark_read

`{channel_id, last_message_id}` → `{"ok": true, "unread": 0}`.
Требует членства в канале.

### POST /channel/filters

Персистентные фильтры потоков record-канала (настройка отображения).
`{channel_id}` — прочитать, `{channel_id, filters: {"change": true}}` —
дописать переданные ключи.

```json
{"channel_id": 21,
 "filters": {"comment": true, "note": true, "message": true,
             "change": true, "activity": true}}
```

## Лента Changes

### POST /changes/feed

`{before_id?, limit?}`. `before_id` — `last_message_id` последнего
показанного элемента. Если личного канала ещё нет —
`{"channel_id": null, "items": []}`.

```json
{
  "channel_id": 33,
  "items": [
    {
      "res_model": "res.partner",
      "res_id": 14,
      "record_name": "Deco Addict",
      "last_message_id": 120,
      "unread": true,
      "changes": [
        {
          "message_id": 120,
          "date": "2026-08-18 11:20:00",
          "author": "Bob",
          "author_id": 11,
          "values": [
            {"field_id": 77, "field_name": "email", "field_desc": "Email",
             "old": "a@x.com", "new": "b@x.com"}
          ]
        }
      ]
    }
  ]
}
```

Показываются только записи, доступные пользователю, и только поля из
его подписки.

## Подписка на поля

### POST /fields/subscription

Без `field_ids` — прочитать состояние:

```json
{
  "res_model": "res.partner",
  "res_id": 14,
  "subscribed": false,
  "field_ids": [77, 78],
  "available_fields": [
    {"id": 77, "name": "email", "field_description": "Email", "tracking": true}
  ]
}
```

Пока подписки нет, `field_ids` — предзаполнение трекаемыми полями.
С `field_ids: [...]` — сохранить выбор (пустой список = отписка); ответ
без `available_fields`. Нужно право чтения записи.

## Уведомления (Notify)

### POST /notify/feed

`{box: "received"|"sent", before_id?, limit?}` → `{"items": [...]}`.

Элемент ленты:

```json
{
  "id": 7,
  "date": "2026-08-18 10:00:00",
  "author": {"id": 6, "name": "Alice"},
  "body": "<p>Позвони клиенту</p>",
  "is_sticky": false,
  "timeout": 10,
  "res_model": "res.partner",
  "res_id": 14,
  "record_name": "Deco Addict",
  "attachments": [ {"id": 5, "name": "spec.pdf", "mimetype": "...", "size": 1} ],
  "voice": {"id": 6, "mimetype": "audio/webm", "duration": 12},
  "transcript": null,
  "transcript_state": "none",
  "parent_id": null,
  "read_date": false,
  "popup_shown": true
}
```

В `received` добавлены `read_date`/`popup_shown` получателя, в `sent`
вместо них `recipients: [{user_id, name, read_date}]`.

### POST /notify/send

`{body, user_ids, attachment_ids?, is_sticky?, timeout?, res_model?,
res_id?}` → `{"id": 8}`. Получатели — только активные внутренние
пользователи, иначе `bad_request`.

### POST /notify/reply

`{parent_id, body, attachment_ids?, is_sticky?, timeout?}` → `{"id": 9}`.
Получатель — автор родительского уведомления; не переданные
sticky/timeout наследуются от родителя.

### POST /notify/mark_read

`{notify_ids: [7, 8]}` → `{"counter": 0}` (актуальный счётчик
непрочитанных).

### POST /notify/popup_shown

`{notify_ids: [7]}` → `{"ok": true}`. Попап не всплывёт повторно.

## Poll (замена longpolling)

### POST /poll

`{last_bus_id}` (0 при первом запросе) → уведомления шины **только
собственного** партнёра пользователя, до 100 за запрос:

```json
{
  "last_bus_id": 512,
  "notifications": [
    {"id": 510, "type": "discuss.channel/new_message",
     "payload": {"id": 21, "data": { ...Store-payload... }}},
    {"id": 511, "type": "streams.notify/new", "payload": { ... }},
    {"id": 512, "type": "streams.changes/updated", "payload": {"id": 33}}
  ]
}
```

Следующий запрос — с возвращённым `last_bus_id`. Типы совпадают с
веб-шиной: `discuss.channel/new_message`, `streams.notify/new|update|
counter`, `streams.changes/updated`, `mail.record/insert` и т.п.;
неизвестные типы клиент молча пропускает. Если пришло ровно 100
уведомлений — сразу повторить запрос (могли остаться ещё).

## Вложения

### POST (http, multipart) /attachment/upload

Не JSON-RPC: обычный `multipart/form-data` с Bearer-заголовком и одним
файлом (имя поля любое, обычно `ufile`). `csrf` не требуется.

Ответ 200:

```json
{"id": 55, "name": "photo.jpg", "mimetype": "image/jpeg", "size": 123456}
```

Файл создаётся «pending» (привязка к будущему сообщению) и доступен
только загрузившему; `id` передаётся в `attachment_ids` поста или
уведомления. Ошибки: 400 (нет файла), 401 (нет токена), 413 (превышен
лимит — системный параметр `streams.guest_max_upload_mb`).

### GET (http) /attachment/&lt;id&gt;

Скачивание с Bearer-заголовком. Отдаётся, если пользователь читает
запись-владельца вложения (запись канала, уведомление) или это его
собственное pending-вложение; иначе 404 (чужое неотличимо от
несуществующего). Ответ — файл с `Content-Disposition: attachment`.
