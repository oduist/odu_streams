# Фаза 9 — виртуальный чаттер партнёра (Odoo 19)

Контракт исполнителей. Источники: ТЗ — `roadmap.md` §18; решения
пользователя 2026-08-18 — `design-virtual-chatter.md` («Решения по
развилкам», В СИЛЕ); факты ядра 19 — `design-phase9-research.md`
(обязателен к прочтению; НЕ пользоваться клиентской частью
design-virtual-chatter.md — она про мёртвый фреймворк 15).

## 1. Решения (сводно)

| # | Решение | Источник |
|---|---|---|
| Р1 | Хранилище — обычная SQL VIEW `streams_partner_message(message_id, partner_id, commercial_partner_id)` из реестра; замер производительности, эскалация к материализованной таблице только при >~300 мс | пользователь 2026-08-18 |
| Р2 | Врезка — наш форк `mail.message._message_fetch`, ветка `thread._name == 'res.partner'`; роут не трогаем ДЛЯ ВЫБОРКИ | research §1 (разворот против дизайна 15) |
| Р3 | Потребление вьюхи — `Domain('id','in', SQL(...))`, НЕ sudo, НЕ сырой курсор: ACL/пагинация/count — ядровые | research §6 (проверено живьём) |
| Р4 | Over-fetch: итеративный сдвиг курсора `before` в нашей ветке, ≤5 итераций, старт ×4 (лимит в 19 применяется до ACL) | research §2 |
| Р5 | Клиентских патчей привязки сообщений НЕТ (Thread.messages наполняется результатом RPC; ссылка «on <doc>» ядровая и нашим message_patch.js не скрывается) — закрепить тестами | research §3 |
| Р6 | Охват: `res.users.settings.streams_partner_scope` (`direct/related/company`, default `related`), клиент охват в RPC не передаёт | пользователь + research §5 |
| Р7 | Виртуальная часть домена: только потоки comment/note/message/activity (виртуальные `change` и «прочее» отсечены через `_streams_stream_domain`); ветка самого партнёра — без ограничений (§18.4) | пользователь + research §8.2 |
| Р8 | Override роута `/mail/thread/messages` — ТОЛЬКО чтобы сузить `set_message_done` до сообщений самой карточки партнёра (ядро гасит needaction ВСЕХ отданных — нарушало бы §18.6) | research риск 7 |
| Р9 | Сид реестра — в `init()` модели реестра, только для установленных моделей (`crm.lead.partner_id` и далее по списку §18.3 по мере установки модулей); XML-data не используется | research §7.3 |
| Р10 | Живучесть вьюхи: пересоздание в init()/CRUD реестра + сверка в `_register_hook`; если вьюхи нет — деградация в Direct c ERROR-логом, не traceback | research §6.4 |
| Р11 | Ключ Store треда-партнёра `streams_company_scope_available` (bool) через override `res.partner._thread_to_store`: True если `commercial_partner_id != partner` ИЛИ есть дочерние контакты; иначе кнопка Company скрыта | пользователь п.5 + research §4 |
| Р12 | Контекст `streams_partner_direct=True` форсирует Direct (страховка для мобильного API и внутренних вызовов) | research риск 8 |

## 2. WP1 — сервер (+python-тесты)

1. **Модель-реестр `streams.partner.source`**: `model_id` (ir.model, ondelete=cascade),
   `field_id` (ir.model.fields, домен: ttype=many2one, relation=res.partner, store),
   `active`. Валидация: поле обязано быть stored m2o на res.partner; предупреждение
   (не запрет) в UI, если поле related. Уникальность (model_id, field_id).
   Кнопка/метод предпросмотра: `action_preview()` → счётчик сообщений ветки
   (research §7.4). Вью в Settings → Technical (список+форма), ACL: чтение
   base.group_user, CRUD base.group_system.
2. **Генерация вьюхи** `streams_partner_message`: UNION ALL по активным строкам
   реестра: `SELECT m.id AS message_id, r.<field> AS partner_id,
   p.commercial_partner_id FROM mail_message m JOIN <table> r ON m.model='<model>'
   AND m.res_id = r.id JOIN res_partner p ON p.id = r.<field> WHERE r.<field> IS NOT NULL`.
   Пустой реестр → вьюха из `SELECT ... WHERE false` (валидная, пустая).
   Пересоздание: `init()`, create/write/unlink реестра; `_register_hook` — проверка
   существования (`information_schema`/`sql.table_kind`) и пересоздание при пропаже (Р10).
   Идентификаторы экранировать (`psycopg2.sql` / `SQL.identifier`) — имена
   таблиц/полей приходят из данных.
3. **Сид (Р9)**: в `init()` реестра — регистрация пар из списка §18.3 roadmap
   для УСТАНОВЛЕННЫХ моделей (минимум: `crm.lead.partner_id`; остальные —
   `sale.order.partner_id`, `purchase.order.partner_id`, `account.move.partner_id`,
   `stock.picking.partner_id`, `project.task.partner_id` — добавлять только если
   модель есть в env). Не дублировать существующие/архивные строки.
4. **`res.users.settings.streams_partner_scope`** + хелпер
   `res.users._streams_partner_scope()` (учёт контекста Р12).
5. **Ветка в `_message_fetch`** (симметрично канальной): для
   `thread._name == 'res.partner'`, scope != direct →
   `domain & ( direct_part | virtual_part )`, где
   `direct_part = model='res.partner' & res_id=partner.id`,
   `virtual_part = Domain('id','in', SQL(SELECT message_id FROM streams_partner_message WHERE partner_id=%s | commercial_partner_id=%s)) & (comment|note|message|activity)`;
   плюс `message_type != 'user_notification'` на всё (ядровый терм теряется при
   thread=None — как в канальной ветке). Over-fetch по Р4. Деградация Р10.
6. **Override роута** (Р8) в controllers: для res.partner-треда `set_message_done`
   только по сообщениям `model='res.partner' AND res_id=thread.id`.
7. **`res.partner._thread_to_store`** → ключ Р11.
8. **Тесты** (`tests/test_streams_partner_feed.py`, стиль модуля):
   реестр (валидация, уникальность, предпросмотр); вьюха (генерация, пересоздание
   при CRUD реестра, деградация при DROP); лента: direct/related/company
   (фикстуры: компания + 2 контакта + записи с m2o; если crm установлен — crm.lead,
   иначе тестовая ветка через `res.partner.parent_id` РЕЕСТРОМ В ТЕСТЕ);
   виртуальные change/прочее исключены, change самого партнёра виден;
   ACL: пользователь с ir.rule видит подмножество (over-fetch добирает страницу);
   needaction чужой записи НЕ гасится просмотром чаттера партнёра, своей — гасится;
   инвариант §18.5: сообщение лида не появляется в stream_channel_ids канала
   партнёра; счётчики/канал партнёра не изменились; Р12-флаг.
   Прогон: 113 существующих + новые, всё зелёное.

## 3. WP2 — клиент (+Hoot/tour)

1. `static/src/core/common/res_users_settings_patch.js` (или к существующему
   паттерну): `streams_partner_scope = fields.Attr("related")`.
2. `chatter_patch.xml/.js`: btn-group Direct/Related/Company перед
   `o-mail-Chatter-topbarGrow`, только для `thread.model === 'res.partner'`
   и сохранённой записи; Company скрыт без `streams_company_scope_available`;
   активная кнопка из store.settings; клик → `set_res_users_settings` +
   `thread.streamsReloadMessages()` (оптимистично, откат при ошибке).
3. Hoot: переключатель (рендер, скрытие Company, клик → RPC + перечитка —
   onRpc-счётчик `/mail/thread/messages`), ссылка «on <doc>» видна у
   виртуального сообщения в чаттере партнёра (Р5), mock: streams_partner_scope
   в settings + ключ Р11 (+ mock-обработка охвата в fetch — по вкусу).
4. Tour: чаттер партнёра — переключить охват, увидеть перечитку (фикстуры
   python-запускалки).
5. Прогон Hoot/туров — С ХОСТА по рецепту `tests/test_js.py` + roadmap
   «To check» (chrome 1148 + LD_LIBRARY_PATH + https-прокси +
   --ignore-certificate-errors); в контейнере браузера нет.

## 4. Вне объёма фазы

Замер на прод-копии (нет копии; To check), материализованная эскалация,
хук-метод для моделей со связью через хоп (§18.3 — заготовить точку
`_streams_partner_source_domain`? НЕТ — отложено до появления таких моделей),
squash-полировка (проверить визуально, чинить только если реально ломается).

## 5. Приёмка

Инварианты AGENTS.md; §18.4–18.6 дословно; 113+ python зелёные; Hoot/tour
зелёные с хоста; живая DOM-проверка (двумя пользователями с разными правами);
roadmap «Сделано → Фаза 9» + хвосты в To check.
