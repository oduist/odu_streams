# streams — Дизайн Фазы 2 (Changes: подписка на поля и личный канал)

Реализует §4.3, §8 и кнопку Changes из §11.1 ТЗ (`roadmap.md`).
Фазы 1a/1b сделаны: подтип `streams.mt_change` уже проставляется на
схлопнутые tracking-сообщения (override `_message_log`), сообщения линкуются
с каналами через m2m `mail.message.stream_channel_ids`, у `mail.channel` есть
`channel_kind='changes'` и `owner_user_id`, unread-механика форкнута,
клиентские патчи messaging-моделей живут в `static/src/models/`.

Порядок работ: сначала сервер + тесты (раздел А), потом UI (раздел Б), потом
браузерный прогон (раздел В). Не начинай UI, пока серверные тесты не зелёные.

## А. Сервер

### А1. Модель `mail.field.subscription`

| Поле | Тип |
|---|---|
| `user_id` | m2o res.users, required, ondelete cascade, index |
| `res_model` | char, required |
| `res_id` | integer, required |
| `field_ids` | m2m ir.model.fields (домен по res_model) |

- SQL unique `(user_id, res_model, res_id)`; индекс `(res_model, res_id)`.
- ACL: пользователь видит/правит только свои подписки (ir.rule по user_id);
  create/write/unlink для base.group_user.
- При удалении записи-источника подписки чистить не обязательно (проверка
  `exists()` на чтении), но заведи хук `unlink` не нужно — не усложняй.
- `ir.model.fields` при удалении поля сам чистит m2m.

### А2. API подписки (RPC для диалога)

На `mail.thread` (или abstract-хелпер на mail.field.subscription):

- `streams_get_field_subscription()` — для текущего пользователя и `self`
  (ensure_one): вернуть {'subscribed': bool, 'field_ids': [...],
  'available_fields': [{id, name, field_description, tracking}, ...]}.
  `available_fields`: только поля, которые пользователь МОЖЕТ читать — поля с
  `groups=` проверяются через доступность в `fields_get()` от имени
  пользователя (fields_get не возвращает поля, к которым нет доступа — §8.1
  «не показываются вовсе»). Исключить служебные (`message_*`, `activity_*`,
  `write_*`, `create_*`, `__last_update`, o2m/m2m технические — бинарные и
  compute-поля без хранения показывать можно, но трекинг по ним всё равно не
  пишется: не фильтруй сверх ядрового «трекается ли», просто отдай флаг
  tracking).
  Если подписки ещё нет — «предзаполнение»: `field_ids` = поля с
  `tracking=True` из fields_get (только предложение, не запись в БД).
- `streams_set_field_subscription(field_ids)` — upsert записи подписки; пустой
  список = отписка (unlink записи).

### А3. Личный канал Changes

- `_streams_get_changes_channel(user)` (helper на mail.channel, sudo):
  найти/создать канал `channel_kind='changes'`, `owner_user_id=user`,
  `channel_type='channel'`, `public='private'`, name='Changes',
  единственный участник — сам пользователь. Частичный UNIQUE-индекс
  `(channel_kind, owner_user_id) WHERE channel_kind != 'record'` (или
  отдельный WHERE channel_kind='changes').
- Канал создаётся лениво: при первой подписке пользователя на поля.
- В `channel_info` он уже отдаёт `channel_kind` (фаза 1b) — клиенту хватит.

### А4. Маршрутизация change-сообщений

Точка: change-сообщение создаётся в `_message_log` (см. фазу 1a) и уже
линкуется с каналом записи в `mail.message.create`. Дописать:

- после создания change-сообщения найти `mail.field.subscription` по
  `(res_model, res_id)`, отфильтровать тех, у кого пересечение
  `field_ids` с фактически изменёнными полями (поля берутся из
  `tracking_value_ids.field` — это m2o на ir.model.fields);
- для каждого такого пользователя — get-or-create его канала Changes и
  линковка сообщения (батчевый `_streams_insert_links`);
- автор изменения обрабатывается наравне со всеми (§8.2);
- сообщение «одно на write»: НЕ создавать персональных копий.
- Массовые операции: сбор подписок одним search по (model, ids), линковка
  одним insert.

### А5. Выдача ленты Changes (свой RPC, не message_format)

Фильтрация tracking_value по подписке и группировка по записям делаются
СЕРВЕРНО, отдельным методом на mail.channel (для channel_kind='changes'):

`streams_changes_feed(limit=30, before_id=None)` возвращает элементы вида:

```
{ 'res_model': ..., 'res_id': ..., 'record_name': ...,
  'last_message_id': ..., 'unread': bool,
  'changes': [ { 'message_id': ..., 'date': ..., 'author': ...,
                 'values': [ {'field_desc': ..., 'old': ..., 'new': ...} ] } ] }
```

- элементы = записи-источники, отсортированы по id последнего изменения
  (новые сверху, §8.3);
- `values` — только tracking_value подписанных полей пользователя И только
  поля, которые пользователь может читать (повторная проверка fields_get —
  подписка могла пережить смену прав); старое/новое — через
  `mail.tracking.value.get_display_value('old'/'new')`;
- изменения записей, к которым пользователь потерял доступ (`ir.rule`,
  `check_access_rights/rule` на чтение) — скрываются целиком (§8.4,
  ретроактивно), сама привязка в БД сохраняется;
- сообщение, у которого после фильтрации не осталось values, не показывается;
- unread по ЗАПИСЯМ: запись непрочитана, если её last_message_id >
  seen_message_id участника канала.

### А6. Unread канала Changes

Форк `_compute_message_unread` (фаза 1a) дополняется веткой для
`channel_kind='changes'`: счётчик = число ЗАПИСЕЙ-источников, у которых есть
непрочитанные change-сообщения (COUNT(DISTINCT (msg.model, msg.res_id)) по
проекциям новее seen_message_id). Обрати внимание: в 1a change-сообщения
исключены из unread — это правило канала ЗАПИСИ; для канала changes они
наоборот единственный источник счётчика.

Прочитанность «при скролле мимо» (§8.3): клиент шлёт
`_channel_seen(last_message_id)` по мере доскролла (ядровая механика seen уже
расширена проекциями в 1a) — по записям это отработает автоматически, т.к.
unread считается от seen_message_id.

### А7. Тесты (обязательные)

1. Подписка: upsert/уникальность; пустой список = unlink; ir.rule «только
   свои».
2. `streams_get_field_subscription`: предзаполнение tracking-полями при
   отсутствии подписки; пользователь без доступа к полю с `groups=` не видит
   его в available_fields (взять поле с groups="base.group_system" и
   обычного пользователя).
3. write с изменением 2 полей, подписчик на 1 из них: сообщение одно,
   слинковано с каналом записи И личным каналом; в `streams_changes_feed`
   подписчик видит только своё поле.
4. Подписчик, не являющийся участником канала записи, получает изменения в
   личный канал (§8.1).
5. Автор изменения, подписанный на поле, видит своё изменение (§8.2).
6. Изменение поля, на которое никто не подписан: линковки с личными каналами
   нет (только канал записи, если тот существует).
7. Unread канала Changes: две записи, по два изменения в каждой → счётчик 2;
   после `_channel_seen` — 0; новое изменение поднимает запись наверх ленты.
8. Потеря доступа: ir.rule закрывает запись → элемент исчезает из
   `streams_changes_feed`, счётчик пересчитывается.
9. Массовый write по 50 записям с одним подписчиком: одно сообщение на
   запись, линковка батчевая (проверить количеством SQL — хотя бы smoke).

## Б. UI

### Б1. Кнопка Changes в чаттере (§11.1)

- Кнопка «Changes» в `chatter_topbar.xml` (рядом с Send Message; паттерн
  фазы 1b — t-inherit extension + `registerInstancePatchModel('mail.chatter')`).
- Клик открывает диалог (OWL Dialog или act_window на TransientModel-визард —
  выбери проще; TransientModel-визард с m2m checkboxes полей приемлем и
  дешевле: `streams.field.subscription.wizard` с полем m2m ir.model.fields и
  доменом по модели, default из `streams_get_field_subscription`).
  Требования §8.1: предотмечены tracking-поля при первом открытии; выбор
  пользователя приоритетен и сохраняется; поля без доступа не показываются.
- Кнопка доступна и не-участникам канала.

### Б2. Личный канал Changes в Discuss

- Канал появляется в сайдбаре у владельца (он участник — попадает в
  init_messaging автоматически). Маршрутизация в категорию: kind='changes' →
  отображать НАД категорией Messages отдельным пунктом (без своей категории:
  один канал; проще всего — в существующей категории Messages первым
  элементом или отдельная мини-категория «Changes»; выбери меньший объём кода
  и опиши решение в отчёте).
- Вид ленты: для `channel_kind='changes'` вместо стандартного ThreadView —
  свой OWL-компонент: список записей (аккордеон/карточки), внутри — изменения
  «поле: было → стало», данные из `streams_changes_feed`. Имя записи
  кликабельно → открыть запись (используй сервис из `bus_actions` открытия
  записи или стандартный action-сервис `action.doAction` с res_model/res_id).
- Поднятие наверх при новых изменениях: при bus `mail.channel/new_message` по
  этому каналу — перезагрузка/инкрементальное обновление фида.
- Read-on-scroll: IntersectionObserver по элементам списка; когда элемент
  записи полностью показан — слать seen до его last_message_id (дебаунс).
  Счётчик в сайдбаре обновляется штатно.

### Б3. Что НЕ делать

- Не трогать рендер change-сообщений в канале ЗАПИСИ (там ядровый tracking
  рендер, фильтр Changes из 1b уже работает).
- Не делать подписку «на уровне модели» (вне рамок, §16).
- Личный канал Notifications — фаза 3.

## В. Браузерный прогон (обязателен)

Среда: worried-horse, https://velesagro11.dev.oduist.com, admin /
30fd9f623658cae7. Webclient рабочий. ВАЖНО: скриншоты фоновой вкладки не
рисуются на этой машине — проверяй по DOM через evaluate_script, скриншоты не
обязательны. Если browser-rendering недоступен/429 — используй
mcp__paseo__browser_* (new_tab/navigate/evaluate/logs/close_tab).

1. Логин; открыть партнёра; кнопка Changes видна; открыть диалог — tracking
   поля предотмечены; выбрать email, сохранить.
2. Изменить email и phone партнёра (форма или odoo_write) → в Discuss
   появился канал Changes; в ленте — запись-партнёр с одним изменением
   (только email, phone скрыт).
3. Клик по имени записи открывает форму партнёра.
4. Счётчик канала = 1; после скролла/просмотра — 0.
5. Консоль без ошибок streams.

## Процесс

Как в фазах 1a/1b: правка → commit/push (Co-Authored-By: Claude Fable 5
<noreply@anthropic.com>) → сразу `pull_and_apply(env_name="worried-horse",
upgrade="streams")` (новая модель/данные/ассеты — только -u, не restart) →
читать ошибки в ответе → `run_odoo_tests(modules="streams")` (все 23 старых
+ новые должны быть зелёными). Бамп версии streams (минорный, 15.0.1.2.0).
Известный шум прод-шаблона: warnings/ERROR про mcp_server — игнорировать.
По завершении обнови `roadmap.md`: секция «Сделано» (Фаза 2) и
отступления; правила — в `AGENTS.md` модуля.
