# Фаза 5: рабочие правила порта 15 → 19 (для исполнителей файлов)

Проверено по живым исходникам ядра 19 в контейнере `streams19`
(`/usr/lib/python3/dist-packages/odoo/addons`, далее `<core>`). Общий
контекст — `design-phase5.md`. Уже портированы (использовать как образец
стиля и API): `models/mail_message.py`, `models/discuss_channel.py`,
`models/discuss_channel_member.py`, `models/mail_thread.py`, `hooks.py`,
`__manifest__.py`.

## Обязательные замены API

| Odoo 15 | Odoo 19 |
|---|---|
| `mail.channel` / `mail.channel.partner` | `discuss.channel` / `discuss.channel.member` (и таблицы `discuss_channel*`) |
| `channel_last_seen_partner_ids` | `channel_member_ids` (в create — команды `(0, 0, {'partner_id': ...})`, whitelist полей: partner_id, guest_id, unpin_dt, last_interest_dt) |
| `'public': 'private'` в vals канала | убрать (поля нет; приватность = членство) |
| `channel.add_members(partner_ids=...)` | тот же метод есть; «joined/left» ядро постит только для channel_type != 'channel' — наши каналы не шумят сами |
| `channel._action_remove_members(partners)` | метода нет: искать `discuss.channel.member` и `unlink()` (с guard-контекстом, если нужно) |
| `channel.channel_rename(name)` | `channel.write({'name': name})` |
| `records.flush()` / `model.flush()` | `records.flush_recordset([...])` / `env[m].flush_model()` |
| `records.invalidate_cache(fnames=, ids=)` | `records.invalidate_recordset(fnames=...)` / `env[m].invalidate_model(fnames=...)` |
| `check_access_rights(op)` + `check_access_rule(op)` | `records.check_access(op)` (raise) / `records.has_access(op)` (bool); модельный уровень без правил — на пустом recordset |
| `name_get()` | `display_name` (перебором записей) |
| `_update_content(...)` на message | `thread._message_update_content(message, ...)` либо `message`-методы 19 — сверять по `<core>/mail/models/mail_message.py` |
| `_get_content_common(...)` (ir.http) | сервис `ir.binary`: `request.env['ir.binary']._get_stream_from(attachment)` → `stream.get_response()` |
| `@http.route(type='json')` | `type='jsonrpc'` |
| `attrs="{'invisible': [...]}"` во вьюхах | прямые выражения: `invisible="state != 'draft'"` и т.п. |
| `<tree>` | `<list>` |
| `expression.AND/OR` | `from odoo.fields import Domain`; `Domain(...) & Domain(...)`, `Domain.AND([...])`, `Domain.OR([...])` |
| `_sql_constraints` | оставлять можно, но новые ограничения — `models.Constraint` / `models.UniqueIndex` классовыми атрибутами (уникальные частичные индексы в `init()` через сырой SQL — переводить на `models.UniqueIndex`) |
| `env['bus.bus']._sendone(target, type, payload)` | остался, но target — recordset (партнёр/пользователь/канал); предпочтительно `record._bus_send(type, payload)` (bus.listener.mixin есть у partner/users/channel/member/message) |
| `env['bus.bus']._sendmany([...])` | УДАЛЁН: цикл `_bus_send` (батчинг делает precommit сам) |
| `bus_actions.signal(...)` | `user.partner_id._bus_send('<type>', payload)` |
| `message.message_format()[0]` / `channel_info()` | `Store`: `from odoo.addons.mail.tools.discuss import Store`; данные клиенту — `Store().add(records).get_result()`; свои ключи модели — override `_to_store_defaults(self, target)` (список имён полей и `Store.Attr('key', value=lambda rec: ...)`) |
| `_init_messaging(self)` → dict | `_init_messaging(self, store)`: `super()._init_messaging(store)`, свои данные — `store.add_global_values(streams_notify={...})` |
| `mail.tracking.value.field` (m2o) | `field_id`; `field_desc` → `field_id.field_description`; `get_display_value('old'/'new')[0]` → `value._format_display_value(value.field_id.ttype, new=False/True)[0]` |
| `message_post(...)` позиционно | все параметры keyword-only |
| `_message_log(subtype_id=...)` | kwarg удалён; подтип Change теперь проставляет `mail.message.create` (`_streams_normalize_tracking_vals`) — отдельных override'ов не нужно |
| `post_init_hook(cr, registry)` | `post_init_hook(env)` |
| `api.Environment(cr, SUPERUSER_ID, {})` в кронах/хуках | у крона в `ir.cron` код получает `env` как раньше (`model.<method>()`), менять не надо |

## Факты ядра 19, важные для наших файлов

- `message_post` сигнатура: `<core>/mail/models/mail_thread.py:2195`;
  нестандартные kwargs нотификации режутся `_get_notify_valid_parameters()`
  (`:3300`), кастомные поля сообщения — `_get_message_create_valid_field_names()`
  (`:3068`).
- `message_type` selection расширен: `email_outgoing`, `auto_comment`,
  `out_of_office`. Классификатор потоков уже учитывает `email_outgoing`.
- Tracking: precommit (`_track_prepare`/`_track_finalize`); в тестах после
  `write()` нужен `self.env.cr.precommit.run()` (или flush-хелпер), иначе
  сообщение ещё не создано. `tracking_value_ids` на message —
  `groups="base.group_system"`.
- unread: считается на `discuss.channel.member` (`message_unread_counter`),
  наш форк — `_streams_compute_record_unread` и ветки changes/notifications
  в `models/discuss_channel_member.py`. Прочтение — `member._mark_as_read`.
- `mail.notify._streams_notify_counter()` остаётся источником счётчика
  Notifications (вызывается из форка unread у member).
- Публичные контроллеры: `request.env` уже с правильным пользователем;
  `request.make_json_response` доступен для http-роутов.
- `res.users.settings` живёт в base (`base/models/res_users_settings.py`),
  `_res_users_settings_format` → в 19 сериализация тоже Store-подобная:
  сверить методы по ядру перед портом полей.
- WebSocket вместо longpolling; гостевая страница остаётся на AJAX-поллинге
  (решение фазы 5), ничего не менять в её архитектуре.
- `queue_job` OCA 19.0 установлен в окружении: `with_delay`,
  `RetryableJobError`, `queue.job.function` — API совместим с 15.

## Чего НЕ делать

- Не трогать `static/legacy15/**` (референс старого веб-клиента) и
  `static/src/guest/**` (переносится as-is).
- Не вызывать Oduflow-инструменты установки/апгрейда (`pull_and_apply`,
  `install_odoo_modules`, ...) — применение и прогон делает координатор.
  Читать ядро 19 можно: `read_file_in_odoo` / `search_in_odoo`
  (env `streams19`, путь `/usr/lib/python3/dist-packages/odoo/addons`).
- Не менять публичные имена методов `streams_*` и контракты RPC — на них
  завязаны тесты и будущий мобильный API.
