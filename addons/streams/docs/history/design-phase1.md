# streams — Дизайн Фазы 1a (серверное ядро)

Исходное ТЗ — `roadmap.md` (рядом) (терминология, §-ссылки ниже — на него).
Этот документ — контракт для исполнителя Фазы 1a. Клиентская часть (OWL/Discuss,
кнопки чаттера, фильтры потоков) — Фаза 1b, здесь НЕ делается.

## Решения, принятые пользователем (не пересматривать)

- Один модуль `addons_veles/streams`.
- Автоподписка вырезается жёстко, без feature-флага.
- Конфликтующий код других модулей вырезается оттуда и поглощается streams
  (первый кандидат — форк автоподписки в `mailgun`).
- Существующие followers на записях НЕ трогаем (чистка партнёров-неюзеров — в
  фазе миграции, не сейчас). Новые записи просто не автоподписывают никого.
- transport ir.rule по `message_partner_ids` не трогаем.
- `mail_activity_custom` обнуляется до пустого shim (создание/цепочки/notify
  оттуда убрать; активности в базе пользователь уже уничтожил).
- crm.lead: каналы видят только собственные сообщения лида; для модели
  `connect_messagebox.message` каналы НЕ создаются (чёрный список).
- В `ai_chat` переименовать «stream» → «ai_chat_stream» (bus-тип
  `ai_chat.stream/update`, JS-переменные, CSS `o_AiChatStream_*`) — освобождает
  префикс для streams (правится и Python, и JS вместе, это простой rename).

## Карта фактов ядра Odoo 15 (проверено по исходникам ~/Dev/odoo_15)

Автоподписка:
- `mail_thread.py:267-274` — create подписывает uid через `_insert_followers`,
  гасится контекстом `mail_create_nosubscribe`.
- `mail_thread.py:276-284` — create вызывает `_message_auto_subscribe`.
- `mail_thread.py:319-326` — write вызывает `_message_auto_subscribe`.
- `mail_thread.py:1894-1895` — `message_post` подписывает partner_ids при
  контексте `mail_post_autofollow` (его ставит композер чаттера из JS).
- `mail_thread.py:1923-1925` — `message_post` подписывает автора (гасится
  `mail_create_nosubscribe`).
- Автор из mail gateway: `mail_thread.py:1081-1082` (`message_new`).

Рассылка:
- Цепочка: `message_post` → `_notify_thread` (`mail_thread.py:2208-2235`):
  `_notify_compute_recipients` → **ранний return при пустых получателях
  (2228-2229)** → `_notify_record_by_inbox` → `_notify_record_by_email`.
- Получатели только из followers + явных partner_ids
  (`mail_followers.py:77-160`, raw SQL).
- Классификация: `type=='user'` = внутренний пользователь
  (`mail_thread.py:2516-2530`).
- `mail.wizard.invite.add_followers` (`mail_wizard_invite.py:74-84`) зовёт
  `_notify_record_by_email` НАПРЯМУЮ с зашитым `notif='email'` — поэтому
  фильтровать надо по `r['type'] != 'user'`, а не по `notif`.

Каналы:
- В 15 у `mail.message` НЕТ связи с каналами: сообщения канала хранятся как
  `model='mail.channel', res_id=channel.id`.
- Участники: `mail.channel.partner` (`channel_last_seen_partner_ids`);
  `channel_partner_ids` — compute/inverse/search, не настоящий m2m.
- unread: `mail_thread.py:179-198` `_compute_message_unread` — raw SQL с
  джойном `cp.channel_id = msg.res_id` и `msg.model='mail.channel'`;
  needaction: `mail_thread.py:200-214`. Наследуются каналом — проекции чужих
  сообщений в них не попадут, надо форкать SQL на `mail.channel`.
- seen: `_channel_seen` (`mail_channel.py:951-973`), `_set_last_seen_message`
  (975-993), `_channel_last_message_ids` (1172-1183, raw SQL) — все с зашитым
  `model='mail.channel'`.
- Выдача: `/mail/channel/messages` — домен зашит инлайн в контроллере
  `addons/mail/controllers/discuss.py:384-391` (не в `_channel_fetch_message`!).
  Override контроллера обязан иметь пустой декоратор `@http.route()`.
  `_channel_fetch_message` (`mail_channel.py:830-841`) — переопределить тоже.
- bus: `mail.channel._notify_thread` (`mail_channel.py:556-573`) →
  `_channel_message_notifications` (711-727), тип `'mail.channel/new_message'`.
  Подписка юзера на bus-канал — серверная, через членство `mail.channel.partner`
  (`mail/controllers/bus.py:22-36`).
- ВАЖНО: broadcast проекций нельзя делать после `super()._notify_thread()` —
  ранний return при пустых получателях. Делать до super либо в
  `_message_post_after_hook` (`mail_thread.py:1939`, вызывается до
  `_notify_thread`).
- ACL: `mail.message._search`/`check_access_rule` фильтруют по правам на
  исходную запись — участник канала без прав на запись получит «дырявую» ленту
  (это нам подходит), но bus-уведомление с полным body уходит всем участникам
  без проверки — нужен гейт при рассылке.
- У `mail.channel` нет `company_id` — добавляем своё.
- `mail.channel._message_subscribe` кидает UserError (`mail_channel.py:678-681`)
  — followers на каналах невозможны, наша синхронизация идёт только через
  `mail.channel.partner`.

Tracking/подтипы:
- Схлопывание изменений в одно сообщение уже есть: `message_track`
  (`mail_thread.py:590-630`) постит ОДНО сообщение со всеми
  `tracking_value_ids`.
- Контекст `mail_track_log_only` (ядро, `mail_thread.py:620`) пропускает
  `_track_subtype` → сообщение уходит через `_message_log` без подтипа и
  рассылки. `mail_extra_recipients/models/mail_thread.py:36` уже ставит этот
  контекст на ВСЕ tracking-записи.
- Серверный дефолт подтипа `message_post` — `mt_note`
  (`mail_thread.py:1888-1891`); `mt_comment` приходит от клиента.
- `message_format` отдаёт клиенту только `is_note`/`is_discussion` — свои
  подтипы надо добавлять в payload отдельным ключом (пригодится в 1b).
- `_get_auto_subscription_subtypes` / `_default_subtypes` — ormcache, при
  правках подтипов не забыть про кэш.

Имя канала:
- Надёжного хука на смену display_name НЕТ (не-stored compute с depends только
  на `_rec_name`; у большинства целевых моделей name_get переопределён).
  Механизм: write-override с фильтром «интересных» полей + ленивая досверка в
  message_post. Переименование через `channel_rename()`
  (`mail_channel.py:1034-1040`) — он шлёт bus `mail.channel/insert`.

## Конфликты в addons_veles (проверено разведкой)

- `mailgun/models/mail_thread.py` — `_message_auto_subscribe` (:49) и ПОЛНАЯ
  КОПИЯ ядрового `_message_subscribe` (:53) с флагом `disable_auto_subscribe`.
  Убрать оба override из mailgun (fetch-логику `message_process` с
  `mailgun_message_url` сохранить); бамп версии mailgun.
- `mail_extra_recipients` — `message_post`/`message_notify`/`message_track`
  overrides; его публичные хелперы (`_message_send_to_extra_emails`,
  `_message_body_with_signature`) используют 3 других модуля — НЕ ломать.
  streams должен зависеть от `mail_extra_recipients` (MRO после него).
- `mail_extra_recipients/controllers/discuss.py` —
  `_get_allowed_message_post_params` whitelist: любые новые kwargs message_post
  из JS должны добавляться туда (актуально для 1b).
- `queue_job.py:349-356` — явный `message_subscribe` менеджеров при падении
  job: публичный API подписки ОСТАЁТСЯ рабочим, ломать нельзя.
- `veles_invite_followers` — уже фильтрует invite-визард доменом
  `[('user_ids','!=',False)]`, но только во вьюхе; streams добавляет серверное
  ограничение.
- `supply_wagon_tracking/models/wagon_update.py:380` — `_notify_followers`
  постит mt_note ради рассылки followers: после Фазы 1 письма не уйдут
  (останется inbox/канал). Осознанно, зафиксировать в отчёте.
- `supply/data/mail_channel.xml` — статический канал уведомлений: новые поля
  канала должны корректно дефолтиться (channel_kind=False для обычных каналов).
- `velesagro_account/payment_confirmation_delivery.py:399` — прямые
  `mail.message` c `message_type='user_notification'` — не трогать, наша
  классификация должна их игнорировать (не триггер канала).

## Состав Фазы 1a

### 1. Скелет модуля
`addons_veles/streams`: `__manifest__.py` (name "Streams", version 15.0.1.0.0,
depends: `mail`, `mail_extra_recipients`, `mailgun`, `bus_actions`;
category Discuss; description по ТЗ). Без type hints; UI-строки английские;
комментарии/докстринги русские.

### 2. Подтипы (data/mail_message_subtype_data.xml)
- Переиспользуем `mail.mt_note` (заметка) и `mail.mt_comment` (комментарий).
- Новые: `streams.mt_message` (Message — внешняя переписка, internal=False,
  default=False), `streams.mt_change` (Change, internal=True, default=False,
  hidden=True), `streams.mt_activity` (Activity, internal=True, default=False,
  hidden=True).
- Классификатор `mail.message` → поток (метод `_streams_classify()` на
  mail.message или mail.thread): по subtype и message_type:
  - subtype mt_note → note; mt_comment → comment; mt_message или
    message_type='email' (входящие) → message; mt_change → change;
    mt_activity → activity; всё прочее (mt_job_failed, user_notification,
    auto-log «запись создана», notification) → «прочее», канал НЕ триггерит.

### 3. Расширение mail.channel (models/mail_channel.py)
Поля: `channel_kind` (selection: record/changes/notifications, без default),
`res_model` (char), `res_id` (integer), `owner_user_id` (m2o res.users),
`company_id` (m2o res.company). Индекс `(res_model, res_id)` через `init()`.
`_sql_constraints`/constrain: уникальность record-канала на (res_model,res_id).

### 4. Проекция сообщений (models/mail_message.py)
`stream_channel_ids = Many2many('mail.channel',
'mail_message_stream_channel_rel', 'message_id', 'channel_id')`.
В `message_format` добавить ключ `stream_channel_ids` (список id) и
`streams_kind` (результат классификации) — заготовка для 1b.

### 5. Ленивое создание канала записи (models/mail_thread.py)
- Хук в `_message_post_after_hook` (или в message_post до notify):
  классифицировать сообщение; если поток ∈ {comment, note, message, activity} —
  `_streams_get_or_create_channel()`; связать сообщение с каналом (m2m).
- При создании канала: name = display_name записи (`sudo`), channel_type
  'channel', public='private', channel_kind='record', res_model/res_id,
  company_id записи (если есть поле), участники = текущие followers-юзеры
  записи; подшить ВСЮ историю сообщений записи (включая старые tracking) —
  батчевым SQL insert в rel-таблицу.
- Изменения (change) и «прочее» канал не создают, но если канал УЖЕ есть —
  change-сообщения тоже линкуются (для фильтра Changes в 1b).
- Чёрный список моделей: `mail.channel`, `connect_messagebox.message`,
  `mail.activity`, transient-модели. Хук `_streams_channel_enabled()` на
  mail.thread (по умолчанию True, blacklist проверяется в одном месте).
- Новое сообщение в архивированной записи → канал разархивируется (§5.5).

### 6. Bus-доставка проекций
- На mail.thread: в том же хуке (до `_notify_thread`, см. факты) собрать
  каналы сообщения и разослать
  `_channel_message_notifications`-подобный payload
  (`'mail.channel/new_message'`) через `bus.bus._sendmany`.
- ACL-гейт: рассылать только тем участникам, у кого есть доступ к записи
  (браузим запись как участник: `record.with_user(u)._filter_access_rules('read')`
  батчево; для record-каналов). Утечка body участнику без прав недопустима.
- Не слать bus дважды для сообщений, чей model уже 'mail.channel'.

### 7. Синхронизация followers ↔ участники (двусторонняя, §5.3)
- `message_subscribe`/`message_unsubscribe` (mail.thread) → зеркалить в
  участников record-канала (если канал существует; создание канала подписка НЕ
  триггерит).
- `mail.channel.partner` create/unlink на record-канале → зеркалить в
  followers записи.
- Guard от рекурсии: контекст `streams_sync=True` — при его наличии зеркало не
  вызывается.
- Followers — только внутренние пользователи: в `message_subscribe` отбросить
  партнёров без внутреннего пользователя (share=True или без user), с
  debug-логом. Явные вызовы (queue_job) продолжают работать — их партнёры
  внутренние.
- `mail.wizard.invite`: серверный домен
  `[('type','!=','private'), ('user_ids.share','=',False)]` + фильтрация в
  `add_followers`.
- В `add_followers` подавить прямую отправку email (`_notify_record_by_email` с
  зашитым notif='email') — приглашение внутренних не шлёт писем.

### 8. Вырезание автоподписки (models/mail_thread.py)
Как в карте фактов:
- `create`: `with_context(mail_create_nosubscribe=True)`.
- `message_post`: контекст без `mail_post_autofollow` + `mail_create_nosubscribe`.
- `_message_auto_subscribe` → no-op (return True).
- `_message_auto_subscribe_notify` → no-op.
- Из mailgun удалить его форк (см. конфликты).
- ВНИМАНИЕ: no-op затрагивает и создание mail.channel (он тоже mail.thread) —
  членство каналов идёт через mail.channel.partner и не страдает; проверить
  тестом.

### 9. Запрет email внутренним (models/mail_thread.py, res_users)
- `_notify_record_by_email`: отфильтровать `r['type'] == 'user'` (покрывает и
  invite-визард).
- `res.users`: default `notification_type='inbox'`; при create/write форсить
  'inbox' для внутренних; post_init_hook — перевести существующих внутренних на
  inbox.
- Системные письма (сброс пароля, приглашение) не трогаем — они идут не через
  `_notify_thread`.

### 10. Имя канала (§5.2)
- `write`-override mail.thread: если запись имеет record-канал и
  `set(vals) & set(self._streams_name_trigger_fields())` — сверить
  `channel.name != display_name` → `channel_rename()`.
- `_streams_name_trigger_fields()`: по умолчанию `[self._rec_name]`, модели
  могут расширять.
- Ленивая досверка в message_post-хуке (display_name там уже вычислен).

### 11. Архивация и merge (§5.5, §5.6)
- `write` на записи с 'active' в vals → синхронизировать `channel.active`.
- `message_change_thread` (используется merge-механиками) → перенести связи
  сообщений и слить каналы: канал источника архивируется, его сообщения
  перелинковываются на канал получателя, участники объединяются.

### 12. Unread (§5.7) — серверная часть
- Форк на mail.channel: `_compute_message_unread` — свой SQL: обычные
  сообщения канала UNION проекции из rel-таблицы, с условием
  `seen_message_id IS NULL OR seen_message_id < msg.id`, ИСКЛЮЧАЯ сообщения с
  подтипом mt_change (§5.7: change не влияет на unread).
- `_channel_seen` / `_set_last_seen_message` / `_channel_last_message_ids` —
  расширить домены/SQL на проекции (иначе seen никогда не догонит).
- `/mail/channel/messages` — override контроллера (ОБЯЗАТЕЛЬНО пустой
  `@http.route()`), домен: `('model','=','mail.channel') & res_id == id` OR
  `stream_channel_ids in [id]`, message_type != 'user_notification'.
  `_channel_fetch_message` — аналогично.

### 13. Синтетические activity-сообщения (§13)
- `mail.activity`: create / write (перенос даты, смена ответственного) /
  unlink-отмена / `_action_done` → `message_post` на записи-источнике с
  subtype `streams.mt_activity`, короткое английское описание события
  (Activity scheduled/rescheduled/reassigned/cancelled/done: summary, deadline,
  assignee). Автор — актор; для automated-контекстов (uid==odoobot/суперюзер
  из крона) — OdooBot.
- Эти сообщения — триггер создания канала (§5.1), но НЕ уведомляют никого
  (subtype internal, рассылки нет — followers-механика на них не сработает,
  т.к. подтип не в подписках по умолчанию).
- `mail_activity_custom` обнулить: удалить models/, data/, hooks — оставить
  пустой манифест-shim (как mail_activity_manual_only), бамп версии, комментарий
  «marked for removal».

### 14. Тесты (tests/)
Обязательные сценарии (TransactionCase, res.partner или транспортная модель как
подопытная — модель с mail.thread):
1. create записи → followers пусто (нет uid, нет user_id), канала нет.
2. write tracked-поля → канала нет; сообщение change создано одно на write.
3. message_post comment → канал создан, история подшита (включая старые
   change), участники = followers на момент создания.
4. note/внешний email (message_new путь) → канал создан.
5. mt_job_failed / user_notification / лог создания → канал НЕ создан.
6. message_subscribe → участник появился; выход из канала → follower снят;
   рекурсии нет (guard).
7. Подписка партнёра-неюзера отбрасывается; queue_job-сценарий (подписка
   менеджеров) работает.
8. Переименование записи (rec_name) → канал переименован.
9. archive/unarchive записи → active канала синхронизирован; сообщение в
   архивированную запись реанимирует канал.
10. Внутренний пользователь не получает email при message_post с его
    partner_ids (mail.mail не создаётся / notification type inbox); внешний
    партнёр при явной отправке — получает.
11. unread: комментарий инкрементит счётчик участника, change — нет.
12. activity create/done → синтетические сообщения, автор корректен.
13. blacklist: message_post в connect_messagebox.message канал не создаёт.

### Вне 1a (не делать сейчас)
JS целиком (категория сайдбара, фильтры потоков, кнопки чаттера, композер,
переименование ai_chat JS можно сделать здесь только в Python+JS rename без
перестройки), mail.field.subscription, mail.notify, гостевой доступ, чистка
followers, классификация исторических сообщений, doc/-книга (по решению —
в финальной фазе).
