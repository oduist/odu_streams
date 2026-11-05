I have everything I need. Here is the full text of `docs/design-phase4.md`.

---

# streams — Дизайн Фазы 4 (гостевой доступ клиентов)

Реализует §4.4 ТЗ **с учётом поправки** (модель `mail.channel.external.participant`,
специфика ссылки — отдельными полями, крон смотрит на транспорт участника), §9
целиком, §10 в части «внешний контакт получает письмо только при явной отправке
или дайджесте» и строки §14, относящиеся к гостю.

Фазы 1a/1b сделаны, фаза 2 (Changes) в работе параллельно — её файлы
(`models/mail_field_subscription.py`, `security/`) трогать нельзя. Фаза 4 с ней
не пересекается: общие точки — только `__manifest__.py` (`data`, `depends`,
версия) и `security/ir.model.access.csv`.

Порядок работ: сервер + тесты (раздел А) → UI (раздел Б) → браузерный прогон
(раздел В). Не начинай UI, пока серверные тесты не зелёные.

---

## Карта фактов ядра (проверено по ~/Dev/odoo_15, 15.0 FINAL)

### Аутентификация и публичные маршруты

- `_auth_method_public` — `odoo/addons/base/models/ir_http.py:107-112`: при пустом
  `request.session.uid` ставит `request.uid = base.public_user` и **сессию не
  трогает**. Отсюда два следствия: `request.session.uid` — надёжный признак
  «это аноним», а личность гостя ядро за нас не хранит — её несём мы сами.
- `_authenticate` — `ir_http.py:114-136`; свои режимы объявляются как
  `_auth_method_<name>` на `ir.http`. Локальный образец —
  `addons_veles/connect_mcp/models/ir_http.py:13-56`.
- CSRF проверяется **только** в `HttpRequest.dispatch` —
  `odoo/http.py:785-819` (`if method not in ('GET','HEAD','OPTIONS','TRACE') and
  routing.get('csrf', True)`), токен = `hmac(secret, session.sid + max_ts)`,
  `csrf_token()` — `http.py:398-416`, сверка `consteq` — `http.py:440`.
- **`type='json'` в 15 CSRF не проверяет вообще**: `JsonRequest.dispatch`
  (`http.py:683-712`) идёт сразу в `_call_function`. `csrf=False` на json-маршруте
  — no-op. Конверт JSON-RPC 2.0, параметры из `params` (`http.py:631`).
- Сессионная кука ставится в `Root.dispatch` — `http.py:1468-1470`
  (`session_id`, `max_age=90 дней`, `httponly=True`, без `secure`/`samesite`).
- `request.render(template, qcontext)` — `http.py:844-859`, ответ **ленивый**:
  `Response.render()` (`http.py:1279-1284`) зовёт `ir.ui.view._render_template`
  только при отдаче, поэтому на возвращённом объекте можно спокойно вызвать
  `set_cookie` — ровно так делает ядро в `addons/mail/controllers/discuss.py:112-117`.
- `request.context` имеет сеттер — `http.py:235-236` (нужно для языка гостя).
- Rate limit в ядре только логинный: `res_users.py:1014-1079`
  (`registry._login_failures` по IP, ICP `base.login_cooldown_after` /
  `base.login_cooldown_duration`), явно помечен как непотокобезопасный
  (`res_users.py:1024-1030`). В `addons_veles` HTTP-троттлинга нет ни одного.

### Куки и токены

- `mail.guest` — эталон куки-идентичности: `_cookie_name='dgid'`,
  `_cookie_separator='|'` (`addons/mail/models/mail_guest.py:18-19`),
  `access_token = uuid4, groups='base.group_system'` (`:26`), разбор куки
  `"<id>|<token>"` + **`consteq`** (`:39-53`), установка куки
  `httponly=True, expires=+365d` (`discuss.py:115-116`).
- Флаги-образец с `samesite`: `addons/auth_totp/controllers/home.py:59-65`
  (`max_age=..., httponly=True, samesite='Lax'`).
- `consteq` — `odoo/tools/misc.py:1526-1531`, импорт `from odoo.tools import consteq`.
- Токены в ядре — `uuid4` (`portal_mixin.py:32`, `ir_attachment.py:663-665`);
  `secrets` в ядре 15 почти не используется, но в репозитории уже есть идиома
  `secrets.token_urlsafe(32)` — `addons_veles/doc_triage_common/models/doc_triage_mixin.py:50`.
  `consteq` в `addons_veles` **не используется нигде** — все локальные проверки
  токенов через `==` (это и есть то, что мы здесь не повторяем).
- Проверка `access_token` у вложений — `ir_http.py:307-340` (`consteq` на :322-324);
  выдача содержимого — `addons/web/models/ir_http.py:124 _get_content_common`
  (образец применения из mail: `discuss.py:156-161`).

### Публичная страница без website

- `web.layout` (`addons/web/views/webclient_templates.xml:9`) и
  `web.frontend_layout` (`:33`) живут в модуле `web`, не в `website`; второй
  тянет `web.assets_frontend` и печатает `odoo.__session_info__`.
- Эталон самодостаточной публичной страницы — `mail.discuss_public_layout`
  (`addons/mail/views/discuss_public_templates.xml:3-35`): собственный `<html>`,
  только свои бандлы, `window.odoo = {__session_info__, csrf_token, debug}`.
- В `addons_veles` публичные страницы уже есть: `supply/controllers/main.py:38-55`
  (`/supply/shipment/<slug>` → `supply.shipment_public`),
  `coa/controllers/main.py:14-16` (`/coa/certificates/<token>` + `request.not_found()`),
  `transport/controllers/main.py:16-50`. `web.layout`/`frontend_layout` локально
  не использует никто.

### Сообщения: публикация, правка, удаление, реакции

- `message_post` — `addons/mail/models/mail_thread.py:1825-1831`, keyword-only.
  `:1874-1875` — **явная проверка прав на чтение записи** (`check_access_rights` /
  `check_access_rule`), поэтому пост от имени гостя обязан идти под `sudo`.
  `:1879-1886` — выбор автора: ветка `mail.guest` работает только при
  `env.user._is_public()` **и** контексте `guest`; иначе
  `_message_compute_author(author_id, ...)` (`:2135-2156`) — явный `author_id`
  партнёра принимается, `email_from` берётся из `partner.email_formatted`.
  `:1923-1925` — автор подписывается на запись, гасится `mail_create_nosubscribe`
  (у нас он уже принудительно стоит: `streams/models/mail_thread.py:133-148`).
- `_notify_thread` — `mail_thread.py:2208-2232`, ранний выход при пустых
  получателях (`:2228`).
- **Правка тела в 15 есть**: `/mail/message/update_content` —
  `addons/mail/controllers/discuss.py:224-236`, модельный метод
  `mail_message.py:679-696`. Гейт `_check_can_update_message_content`:
  общий (`mail_thread.py:1953-1961`) разрешает только `mail.mt_note` без
  tracking и только `message_type='comment'`; `mail.channel`
  (`mail_channel.py:619-623`) **не зовёт super** и разрешает любой comment.
- **Отдельного маршрута удаления нет.** Удаление в клиенте 15 = `update_content`
  с пустым телом и без вложений; строка `mail.message` остаётся,
  `_filter_empty()._cleanup_side_records()` (`mail_message.py:1035-1051`) чистит
  звёзды и нотификации. Клиент пустые сообщения **не рисует вовсе** —
  `components/message_list/message_list.xml:56` (`t-if="!messageView.message.isEmpty"`).
- Реакции: модель `mail.message.reaction` (`addons/mail/models/mail_message_reaction.py:13-24`,
  XOR partner/guest, партиальные уникальные индексы), методы
  `mail_message.py:789-821` (`_message_add_reaction` / `_message_remove_reaction`,
  внутри `check_access_rule('write')` и хуки `_message_*_reaction_after_hook`),
  сериализация в `_message_format` — `mail_message.py:876-892`
  (`messageReactionGroups`). Ядровые маршруты (`discuss.py:304-358`) пускают
  анонима **только** если он `mail.guest` и сообщение лежит на `mail.channel`
  (`:311`, `:339`) — для нас неприменимо.
- Загрузка вложения: `/mail/attachment/upload` (`discuss.py:238-276`) —
  для share-пользователя ядро само генерит `access_token` (`:256-258`).

### Почта: нитка, маршрутизация ответа, шаблоны

- `Message-Id` сообщения формируется в `mail_message.py:1077-1083`
  (`generate_tracking_message_id`, `odoo/tools/mail.py:490-501`), вид
  `<rnd.ts-openerp-{res_id}-{model}@host>`.
- **Обратно из Message-Id ничего не парсится.** Маршрутизация ответа — точный
  поиск по БД: `mail_thread.py:890-899`
  (`search([('message_id','in', msg_references)], limit=1)`), где refs берутся
  из `References`/`In-Reply-To` регуляркой `tools.mail_header_msgid_re`
  (`odoo/tools/mail.py:486`). Значит: **нитка живёт, только если существует
  `mail.message` с ровно этим `message_id`**.
- Ветка «это ответ» — `mail_thread.py:933-966`; прямое письмо на catchall без
  распознанного reply отбивается (`:974`). Обработка маршрута —
  `_message_route_process` (`mail_thread.py:1031-1080`): `message_update` на
  найденном треде, затем `message_post` с `subtype_id = mail.mt_comment`, а при
  `is_internal` — `mail.mt_note`. `is_internal` наследуется от родителя:
  `_message_parse_extract_from_parent` (`mail_thread.py:1499-1507`) —
  `parent_is_internal = parent.subtype_id.internal`. Родитель определяется по
  `in_reply_to`/`references` (`:1480-1493`).
- `reply_to` — `addons/mail/models/models.py:96-172` (`_notify_get_reply_to`):
  сначала алиасы записи, иначе `mail.catchall.alias@mail.catchall.domain`
  (`:157-161`); **без `mail.catchall.domain` возвращается `default`**, то есть
  ответ маршрутизировать некуда.
- Входящая почта в этом деплое приходит вебхуком Mailgun:
  `addons_veles/mailgun/controllers/main.py:10-24` → `mailgun_fetch_message`
  (`mailgun/models/mail_thread.py:16-33`) → ядровый `message_process`. То есть
  §9.7 упирается ровно в ядровую цепочку выше, ничего своего писать не нужно.
- `mail.template.send_mail(res_id, force_send=False, raise_exception=False,
  email_values=None, notif_layout=False)` — `mail_template.py:264-316`;
  `email_values` **перебивает** значения шаблона (`:287`), письмо создаётся как
  `mail.mail` под sudo (`:316`). Язык — поле `lang` рендер-миксина
  (`mail_render_mixin.py:49-53`), в репозитории идиома
  `{{ object.partner_id.lang }}` уже используется:
  `transport/data/mail_template.xml:28,58`, `velesagro_sale/data/sale_order_docs_templates.xml:27`.

### Крон и настройки

- Часовой крон-образец — `addons/mail/data/ir_cron_data.xml:4-14`
  (`noupdate="1"`, `forcecreate="True"`, `state=code`, `interval_type=hours`,
  `numbercall=-1`, `user_id ref="base.user_root"`). Локальный стиль —
  `veles_sales_cockpit/data/ir_cron_data.xml:1-21`.
- `ir.config_parameter.get_param(key, default=False)` возвращает **строку**
  (`odoo/addons/base/models/ir_config_parameter.py:60`), всегда через `.sudo()`.
- `res.config.settings` с `config_parameter=` — образец
  `transeu_bridge/models/res_config_settings.py:11-27` + вьюха
  `transeu_bridge/views/res_config_settings_views.xml:5-45`.

### Что уже есть в streams (фазы 1a/1b)

- Классификатор потоков `_streams_classify_vals(subtype_id, message_type)` —
  `streams/models/mail_message.py:80-109`. Порядок важен: `user_notification`
  → `False`; `message_type='email'` → `message`; наши подтипы; затем
  `message_type='notification'` → `False`; затем note/comment.
- Проекция `stream_channel_ids` (`mail_message.py:45-47`), домен ленты канала
  `_streams_message_domain` (`mail_channel.py:245-250`), подшивка истории
  `_streams_attach_history` (`mail_channel.py:87-105`).
- Ленивое создание канала и рассылка по шине — `mail_thread.py:150-186`
  (`_message_post_after_hook` → `_streams_handle_posted_message`), адресный
  broadcast с ACL — `mail_thread.py:286-352`.
- Автоподписка вырезана, `mail_create_nosubscribe` форсится в `message_post`
  (`mail_thread.py:133-148`); письма внутренним подавлены фильтром
  `type != 'user'` в `_notify_record_by_email` (`mail_thread.py:86-106`).
- Подписать партнёра-неюзера нельзя (`_streams_filter_internal_partners`,
  `mail_thread.py:373-388`), участники канала зеркалятся в followers
  (`mail_channel_partner.py:58-95`).
- Подтипы: `streams.mt_message` (internal=False), `mt_change`, `mt_activity`
  (оба internal=True, hidden) — `data/mail_message_subtype_data.xml`.
- Кнопки и тумблеры в шапке канала — `static/src/models/thread_view_topbar.js`,
  `static/src/xml/thread_view_topbar.xml`.

---

## Решения (и почему именно так)

**Р1. Внешний участник — не член канала и не `mail.guest`.**
Строка `mail.channel.partner` немедленно уехала бы в followers записи через наше
зеркало (`mail_channel_partner.py:58-66`), а followers по §10.3 — только
внутренние; партнёр-неюзер там всё равно отфильтруется
(`mail_thread.py:373-388`), и мы получили бы участника-призрака. `mail.guest`
тянет свою куку, своё членство и `channel_info`, который для публичной сессии
всё равно ничего не отдаёт (`mail_channel.py:784`). Поэтому доступ гостя живёт
**только** в нашей модели, а ядровые механики канала (`channel_info`, unread,
seen, шина) остаются нетронутыми.

**Р2. Свои контроллеры, а не ядровые `/mail/*`.**
Ядровые публичные маршруты пускают анонима исключительно как `mail.guest` и
исключительно к сообщениям с `model='mail.channel'` (`discuss.py:311,339`), а
наши сообщения лежат **на записи** (`model='res.partner'` и т.п.). Патчить их
пришлось бы во всех точках сразу и с риском ослабить ядровую проверку для всех
остальных. Свой префикс `/streams/guest/*` — меньше кода и ровно один вход.

**Р3. Кука-сессия по образцу `mail.guest`, но с флагами.**
Значение `"<participant_id>|<session_token>"`, поиск по id + `consteq` — то же,
что `mail_guest.py:39-53`, без поиска по секрету в БД. Флаги:
`httponly=True`, `samesite='Lax'`, `secure` — по `request.httprequest.is_secure`,
`path='/streams'`, `max_age = срок сессии`. `Lax`, а не `Strict`: переход по
ссылке из письма — это top-level GET, при `Strict` гость приезжал бы «разлогиненным».
`Lax` заодно закрывает CSRF: кросс-сайтовый POST нашу куку просто не понесёт.

**Р4. Одноразовость ссылки: GET показывает, POST сжигает.**
GET `/streams/guest/<token>` только рисует страницу-подтверждение с кнопкой и
`csrf_token` — антифишинговые сканеры почты, прокликивающие ссылки, токен не
жгут (§9.3, риск §17.5). POST проверяется ядровым CSRF (`http.py:785-819`) —
он работает и для анонима, потому что кука `session_id` ставится на GET-ответе
(`http.py:1468-1470`); **`save_session=False` на этих двух маршрутах ставить
нельзя**, иначе токен CSRF перестанет сходиться.
AJAX-маршруты делаем `type='json'` — в 15 они не CSRF-проверяются вовсе
(`http.py:683-712`), а защиту даёт `SameSite=Lax` + обязательный
`Content-Type: application/json` (кросс-доменно это preflight).

**Р5. Страница — свой standalone-QWeb без website, без OWL, без бандлов.**
Берём подход `mail.discuss_public_layout` (`discuss_public_templates.xml:3-35`),
но без `session_info`: гостю нельзя отдавать серверный дамп сессии. CSS и JS —
обычные файлы в `static/src/guest/` (каталог `static` отдаётся публично), никакого
`web.assets_*`: у публичной страницы не должно быть ни одного байта бэкенд-кода.
Язык — `request.context = dict(request.context, lang=partner.lang or 'en_US')`
перед `request.render` (сеттер есть: `http.py:235`).

**Р6. Видимость гостя — один домен, согласованный с классификатором.**
`_streams_guest_message_domain()` на `mail.message` — единственное место, где
описано «что видит гость» (§9.4). Его нельзя вычислять через
`_streams_classify()` построчно (это Python-фильтр по всей ленте), поэтому пишем
домен и **обязательным тестом** сверяем его с `_streams_classify_vals` на наборе
фикстур. Иначе новый подтип разъедет с фильтром молча.

**Р7. Правка — ядровый `_update_content`, удаление — опустошение тела.**
`_update_content` (`mail_message.py:679-696`) уже умеет всё нужное (тело,
вложения, чистку побочных данных). Мешает только гейт
`_check_can_update_message_content`, который на обычной записи разрешает лишь
заметки (`mail_thread.py:1953-1961`) — расширяем его нашим случаем.
Удаление делаем как ядро: пустое тело без вложений. Тогда сообщение исчезает и
в Discuss, и в чаттере (`message_list.xml:56` не рисует пустые), но строка
остаётся — аудит цел, `parent_id` чужих сообщений не рвётся, реакции чистятся.
Реального `unlink` не делаем.

**Р8. Реакции — свой эндпоинт поверх ядрового `_message_add_reaction`.**
Модель `mail.message.reaction` умеет `partner_id` (`mail_message_reaction.py:15`),
а гость у нас — настоящий партнёр, так что реакция гостя неотличима от реакции
человека и корректно отрисуется у сотрудников. Ядровый метод зовём под `sudo`
(он делает `check_access_rule('write')`, которого у публичного юзера нет), но
`author`/`partner_id` берём из `env.user.partner_id`, поэтому вызываем его на
`message.with_user(SUPERUSER).with_context(...)`? — нет: ядровый метод берёт
партнёра из `env.user` (`mail_message.py:796`), поэтому пишем
`mail.message.reaction` напрямую (search-or-create/unlink, 10 строк), не
изобретая обходов вокруг `env.user`.

**Р9. Вложения — свой маршрут с проверкой по сообщению, без токена в URL.**
`/streams/guest/attachment/<id>`: вложение отдаётся, только если оно висит на
сообщении, попадающем в домен Р6 у **этого** участника. Так `access_token` не
светится в URL, не утекает через Referer и не переживает отзыв доступа. Выдача —
`env['ir.http'].sudo()._get_content_common(res_id=...)` (как `discuss.py:161`).
Отдельным пунктом: тела сообщений могут содержать `<img src="/web/image/ID">`
(вставленные картинки) — на рендере переписываем такие ссылки на наш маршрут,
иначе у гостя вместо картинок будут битые иконки.

**Р10. Якорь треда для ответа по email — служебное сообщение «прочее».**
Ответ гостя маршрутизируется только точным совпадением `References` с
`mail.message.message_id` (`mail_thread.py:890-899`), поэтому в БД должно лежать
сообщение-якорь. Ставим его при первом приглашении: `message_post` на записи с
`message_type='notification'` и `subtype_xmlid='mail.mt_comment'`.
Почему именно так: по классификатору (`mail_message.py:103-104`) `notification`
без наших подтипов — «прочее», значит якорь не создаёт канал, не влияет на
unread, не виден гостю и не попадает в потоки §6; а `mt_comment` не internal,
значит `_message_parse_extract_from_parent` (`mail_thread.py:1502-1505`) не
пометит ответ гостя как `is_internal` и ядро запостит его нормальным
`mt_comment`/`message_type='email'` → по нашему классификатору это `message`,
видимое гостю. В чаттере сотрудников якорь читается как строчка аудита
«External participant invited» — это полезно, а не шум.
Предусловие продукта: `mail.catchall.domain` / `mail.catchall.alias` заполнены,
иначе `_notify_get_reply_to` вернёт `default` (`models.py:170-172`) и ответить
будет некуда — проверяем в коде и пишем внятный лог.

**Р11. Дайджест идёт мимо `_notify_thread`.**
Наш запрет рассылки живёт в `_notify_record_by_email` (`streams/models/mail_thread.py:86-106`)
и режет только `type == 'user'`, так что гость-`customer` через него прошёл бы и
так. Но дайджест не должен ни создавать `mail.message`, ни зависеть от followers
— поэтому `mail.template.send_mail(participant.id, ...)` (`mail_template.py:264`),
где `render_model = mail.channel.external.participant`, а язык — `{{ object.partner_id.lang }}`.

**Р12. Ротация ссылки — только если предыдущая уже сожжена.**
§9.6 требует «новая ссылка, старая гасится». Если гость ещё ни разу не входил
(`is_link_consumed=False`), гасить нечего, а ротация убила бы ссылку в
неоткрытом письме-приглашении. Поэтому: `is_link_consumed=True` → новый токен,
старый в ноль; `False` → в дайджест кладём текущую ссылку. Свойства доступа
(`history_from`, `partner_id`, `channel_id`, `anchor_message_id`) переживают
ротацию — это одна и та же строка участника, меняется только секрет.
Кука-сессия при ротации **не** трогается: ротируется ссылка, а не сессия.

**Р13. Транспорт — поле, а не абстракция (поправка ТЗ).**
`transport = Selection([('link', 'Invitation link')])`, крон отбирает
`transport == 'link'`. Когда появится Telegram, добавится значение и ветка в
кроне; ни базового класса, ни реестра транспортов сейчас не заводим.

**Р14. Защиты от перебора токена достаточно длины и `consteq`.**
`secrets.token_urlsafe(32)` — 256 бит (идиома репозитория:
`doc_triage_common/models/doc_triage_mixin.py:50`), это не перебирается.
Отдельный rate limiter не пишем: в ядре его нет, единственный образец
(`res_users.py:1014-1079`) сам себя объявляет непотокобезопасным и работает
внутри одного воркера. Вместо него — `_logger.warning` на каждый промах с IP,
чтобы поведение было видно в логах.

**Р15. ACL модели — только `base.group_system`.**
Модель полностью серверная: обычный пользователь работает через визард
приглашения, который ходит `sudo()`. Одна строка в `ir.model.access.csv` для
`base.group_system` (а не полное отсутствие строк) — чтобы не ловить ядровое
предупреждение «has no access rules» и чтобы админ мог посмотреть/отозвать
доступ руками. Секреты дополнительно закрыты `groups='base.group_system'` на
полях — как `mail.guest.access_token` (`mail_guest.py:26`).

---

## А. Сервер

### А1. Модель `mail.channel.external.participant`

`models/mail_channel_external_participant.py`, `_description = 'Channel External Participant'`,
`_rec_name = 'partner_id'`.

| Поле | Тип | Примечание |
|---|---|---|
| `channel_id` | m2o `mail.channel`, required, index, `ondelete='cascade'` | |
| `partner_id` | m2o `res.partner`, required, index, `ondelete='cascade'` | конкретный контакт, не компания |
| `transport` | Selection `[('link','Invitation link')]`, required, default `'link'` | Р13 |
| `token` | Char, copy=False, index, `groups='base.group_system'` | секрет текущей ссылки |
| `token_date` | Datetime | когда выдана (для логов и дайджеста) |
| `history_from` | Datetime, required, default `now` | §9.2 |
| `session_token` | Char, copy=False, index, `groups='base.group_system'` | |
| `session_expiry` | Datetime | |
| `is_link_consumed` | Boolean, default False | |
| `active` | Boolean, default True | отзыв доступа (§9.3) |
| `last_seen` | Datetime | heartbeat (§9.5) |
| `last_digest_sent` | Datetime | §9.6 |
| `anchor_message_id` | m2o `mail.message`, `ondelete='set null'` | якорь треда, Р10 |
| `invited_by_id` | m2o `res.users`, default `env.user` | кто выдал доступ |
| `res_model` / `res_id` | related `channel_id.res_model` / `.res_id`, store=False | удобство |

Индексы в `init()` (по образцу `streams/models/mail_channel.py:36-52`):

- `UNIQUE ... (token) WHERE token IS NOT NULL`
- `UNIQUE ... (session_token) WHERE session_token IS NOT NULL`
- `UNIQUE ... (channel_id, partner_id) WHERE active` — повторное приглашение
  живого участника обновляет строку, отозванные строки остаются историей
- обычный индекс `(channel_id)` даёт `index=True`.

Ограничения:

- `@api.constrains('channel_id')` — только `channel_kind == 'record'`;
- `@api.constrains('partner_id')` — `not partner_id.is_company` и у партнёра нет
  внутреннего пользователя (внутренних приглашать гостем бессмысленно и опасно).

ACL: одна строка в `security/ir.model.access.csv` на `base.group_system`
(1,1,1,1). `ir.rule` не нужен.

### А2. Токены и сессия

```python
def _streams_new_token(self):
    return secrets.token_urlsafe(32)
```

- `_streams_issue_link()` — новый `token` + `token_date`,
  `is_link_consumed=False`; возвращает абсолютный URL
  `<web.base.url>/streams/guest/<token>`.
- `@api.model _streams_from_token(token)` — `search([('token','!=',False)])`
  по равенству + повторная сверка `consteq(participant.token, token)`;
  дополнительно `active`, живой канал (`channel_id.active`), партнёр существует.
- `_streams_open_session()` — вызывается на POST-подтверждении:
  `session_token = _streams_new_token()`,
  `session_expiry = now + срок`, `is_link_consumed = True`, `token = False`
  (ссылка гаснет физически, а не флагом), `last_seen = now`. Возвращает
  значение куки `f'{self.id}|{session_token}'`.
- `@api.model _streams_from_session(cookie_value)` — split по `|`, `browse(id)`,
  `consteq`, проверки `active` / `session_expiry > now` / `channel_id.active`.
- `_streams_touch(extend_session=True)` — «сердцебиение»: пишет `last_seen`, но
  **не чаще раза в 60 с** (сравнение с текущим `last_seen`), и продлевает
  `session_expiry`, если до конца осталось меньше половины срока. Так
  десятисекундный поллинг не превращается в 8 640 UPDATE в сутки на гостя.
- `_streams_revoke()` — `active=False`, `token=False`, `session_token=False`,
  `session_expiry=False`.

Все методы модели рассчитаны на вызов из-под `sudo` — контроллер ниже другого
режима и не знает.

### А3. Видимость сообщений

На `mail.message`:

```python
def _streams_guest_message_domain(self, participant):
    """Что видит гость (§9.4): комментарии и сообщения его канала с history_from."""
```

Домен:

```
['&', '&',
 ('stream_channel_ids', 'in', participant.channel_id.ids),
 ('date', '>=', participant.history_from),
 '&', ('message_type', 'not in', ('user_notification',)),
      '|', ('message_type', '=', 'email'),
           '&', ('message_type', 'in', ('comment', 'email')),
                ('subtype_id', 'in', [mt_comment_id, mt_message_id])]
```

- `note` / `change` / `activity` не проходят по подтипу; «прочее»
  (`message_type='notification'`, в том числе наш якорь) — по `message_type`;
- пустые сообщения (удалённые гостем или сотрудником) отфильтровываются на
  сериализации, а не доменом (`body` пустой ⇒ пропускаем), — так же, как это
  делает клиент (`message_list.xml:56`).

**Обязательный тест** сверяет домен с `_streams_classify_vals`
(`streams/models/mail_message.py:80-109`) на матрице подтип × message_type.

### А4. Контроллер `controllers/guest.py`

Все маршруты — `auth='public'`, все под `sudo`, все начинаются с одного
хелпера `_streams_participant()` (кука → участник или `NotFound`).

| Маршрут | type | method | Назначение |
|---|---|---|---|
| `/streams/guest/<string:token>` | http | GET | страница подтверждения; ссылку **не** гасит |
| `/streams/guest/<string:token>` | http | POST | обмен ссылки на сессию, `set_cookie`, redirect 303 на `/streams/guest/chat` |
| `/streams/guest/chat` | http | GET | страница чата, продлевает сессию и переставляет куку |
| `/streams/guest/feed` | json | POST | лента + участники (он же heartbeat) |
| `/streams/guest/post` | json | POST | отправка сообщения |
| `/streams/guest/update` | json | POST | правка своего сообщения |
| `/streams/guest/delete` | json | POST | удаление своего сообщения (= пустое тело) |
| `/streams/guest/reaction` | json | POST | `add` / `remove` |
| `/streams/guest/upload` | http, `csrf=False` | POST | вложение (multipart) |
| `/streams/guest/attachment/<int:attachment_id>` | http | GET | выдача вложения |

Отдельного heartbeat-маршрута нет: любой запрос гостя зовёт `_streams_touch()`.

Коды ответов: неизвестный/сожжённый токен и чужое вложение — `NotFound` (404);
протухшая сессия, отозванный участник, архивированный канал — **410 Gone** со
своей страницей «This chat link is no longer active» (для http) и
`{'error': 'gone'}` (для json), чтобы клиентский JS остановил поллинг и показал
человеческий текст, а не крутил спиннер.

Детали:

- **GET по ссылке** рисует `streams.guest_confirm`: имя канала, имя компании,
  кнопка `Enter chat` в форме `method="post"` с
  `<input type="hidden" name="csrf_token" t-att-value="request.csrf_token()"/>`
  (`webclient_templates.xml:137` — образец) и текстом «This link works once».
- **POST** — `_streams_open_session()`, затем
  `response = request.redirect('/streams/guest/chat', code=303)` и
  `response.set_cookie(...)` с флагами из Р3.
- **`/streams/guest/chat`** — `request.render('streams.guest_chat', qcontext)`,
  на ленивом ответе снова `set_cookie` (скользящее окно), в `qcontext` — только
  имя канала, имя гостя, интервал поллинга, окно правки и стартовая порция
  ленты (чтобы первый экран не ждал AJAX).
- **`/streams/guest/feed`** принимает `after_id` (инкремент) либо
  `before_id`+`limit` (подгрузка вверх, по умолчанию 30) и возвращает:

```python
{'channel': {'name': ...},
 'me': {'partner_id': ..., 'name': ...},
 'members': [{'name': ..., 'is_external': bool}, ...],
 'messages': [{'id', 'date', 'author', 'is_own', 'body',
               'attachments': [{'id', 'name', 'mimetype'}],
               'reactions': [{'content', 'count', 'mine'}],
               'editable_until': iso|false}],
 'server_time': iso}
```

  `body` — `message.body` после переписывания `/web/image/<id>` и
  `/web/content/<id>` на `/streams/guest/attachment/<id>` для вложений,
  попадающих в А3; всё остальное `/web/...` из тела вырезается (внутренние
  ссылки гостю бесполезны и говорят лишнего). `author` — `display_name`
  партнёра как есть (§9.4, без подмены на компанию).

### А5. Отправка, правка, удаление, реакции, вложения

**Отправка** (`/streams/guest/post`):

```python
record = request.env[channel.res_model].sudo().browse(channel.res_id)
message = record.with_context(streams_guest_post=True).message_post(
    body=plaintext2html(body_text),
    author_id=participant.partner_id.id,
    message_type='comment',
    subtype_xmlid='streams.mt_message',
    attachment_ids=attachment_ids)
```

- Тело гостя **всегда** приходит текстом и всегда прогоняется через
  `odoo.tools.mail.plaintext2html` (`odoo/tools/mail.py:393`); HTML от гостя не
  принимаем ни при каких условиях. Лимит длины — 10 000 символов.
- `sudo` обязателен: `message_post` проверяет права на чтение записи
  (`mail_thread.py:1874-1875`).
- `message_type='comment'` + `subtype='streams.mt_message'` даёт
  `streams_kind='message'` (`mail_message.py:100-102`) — сотрудникам видно как
  внешнюю переписку, гостю видно по А3.
- Автор не станет follower: `mail_create_nosubscribe` форсится нашим
  `message_post` (`streams/models/mail_thread.py:133-148`), и партнёр-неюзер
  всё равно был бы отфильтрован (`:373-388`).
- Писем не будет: подтип `default=False`, followers на него не подписаны,
  `_notify_thread` выйдет на `:2228`.
- Дальше всё бесплатно: `_message_post_after_hook` (`:150-186`) подошьёт
  сообщение к каналу и разошлёт проекцию сотрудникам по шине; unread канала у
  сотрудников вырастет.

**Правка** (`/streams/guest/update`): проверяем авторство
(`message.author_id == participant.partner_id`), окно (`now - message.date <=
окно правки`), затем

```python
message.sudo().with_context(streams_guest_edit=True)._update_content(
    body=plaintext2html(new_body), attachment_ids=keep_ids)
```

и override на `mail.thread`:

```python
def _check_can_update_message_content(self, message):
    if self.env.context.get('streams_guest_edit'):
        return  # гейт уже отработал в контроллере (авторство + окно)
    return super()._check_can_update_message_content(message)
```

(без него ядро запретит: общий гейт разрешает только заметки —
`mail_thread.py:1953-1961`).

**Удаление** (`/streams/guest/delete`) — те же проверки и
`_update_content(body='', attachment_ids=[])` (Р7). Сообщение исчезает из
Discuss и чаттера (`message_list.xml:56`), строка остаётся.

**Реакции** — прямая работа с `mail.message.reaction` под sudo:
проверить, что сообщение проходит домен А3, затем search-or-create /
unlink по `(message_id, content, partner_id=participant.partner_id)`;
после этого послать сотрудникам тот же bus-пакет, что и ядро
(`mail_channel.py:634-655`: `mail.message/insert` с `messageReactionGroups`),
чтобы у открытого Discuss реакция появилась сразу. Список допустимых `content`
— тот же короткий набор эмодзи, что рисует наша страница; произвольные строки
не принимаем.

**Вложения** (`/streams/guest/upload`): создаём `ir.attachment` с
`res_model='mail.compose.message', res_id=0` (как ядро, `discuss.py:249-255`),
без `access_token` (он нам не нужен — доступ по сессии), возвращаем
`{id, name, mimetype, size}`. Лимиты: размер из ICP (по умолчанию 25 МБ),
не более 10 файлов на сообщение, имя нормализуем. При отправке сообщения
`message_post` сам перепривяжет вложения к записи.

**Выдача вложений**: проверить, что вложение лежит на сообщении из домена А3
(`search([('attachment_ids','in',[id])] + guest_domain, limit=1)`), затем
`request.env['ir.http'].sudo()._get_content_common(res_id=attachment_id, download=download)`.

### А6. Приглашение (§9.2)

Визард `streams.guest.invite.wizard` (TransientModel):

| Поле | Тип |
|---|---|
| `channel_id` | m2o `mail.channel`, required, readonly |
| `partner_ids` | m2m `res.partner`, domain `[('is_company','=',False), ('type','!=','private')]` |
| `history_from` | Datetime, required, default `now` |
| `send_email` | Boolean, default True |
| `state` | Selection `[('draft','Draft'), ('done','Done')]`, default `'draft'` |
| `link_ids` | o2m `streams.guest.invite.wizard.line` (partner_id, url, email_sent) |
| `participant_ids` | m2m `mail.channel.external.participant`, compute — уже выданные доступы канала |

`action_invite()`:

1. на каждый партнёр — `_streams_get_or_create_participant(channel, partner,
   history_from)` (upsert по активному участнику), `_streams_issue_link()`;
2. якорь: если у канала ещё нет `anchor_message_id` ни у одного участника —
   постим служебное сообщение (Р10) и запоминаем его на участнике;
3. `send_email and partner.email` → `mail.template
   streams.mail_template_guest_invite`.`send_mail(participant.id, force_send=True,
   email_values={'email_to': partner.email, 'reply_to': reply_to, 'references':
   anchor.message_id, 'headers': repr({'In-Reply-To': anchor.message_id})})`;
4. заполняем `link_ids`, ставим `state='done'` и возвращаем тот же визард
   (`res_id=self.id`, `target='new'`) — ссылки показываются с
   `widget="CopyClipboardChar"` для ручной передачи (§9.2).

`action_revoke_participant()` (кнопка в строке списка выданных доступов) —
`participant._streams_revoke()`.

Обязательные английские строки визарда:

- заголовок `Invite a customer to this chat`;
- предупреждение (алерт в форме): *«The invited contact will see every comment
  and message in this channel posted after the selected moment, including
  attachments. Notes, field changes and activities stay private.»*
- подпись поля `history_from` — `Show history from`;
- `send_email` — `Send the invitation by email`;
- строка списка ссылок — `Personal link (works once)`.

### А7. Дайджест (§9.6)

`data/ir_cron_data.xml` (по образцу `addons/mail/data/ir_cron_data.xml:4-14`):
`noupdate="1"`, `forcecreate="True"`, `model_id` =
`model_mail_channel_external_participant`, `state=code`,
`code`: `model._cron_streams_guest_digest()`, `interval_number=1`,
`interval_type=hours`, `numbercall=-1`, `user_id ref="base.user_root"`.

`_cron_streams_guest_digest()`:

1. кандидаты: `active`, `transport == 'link'`, `channel_id.active`,
   `partner_id.email` (без адреса дайджест некуда слать — логируем `debug`);
2. отсутствующие: `not last_seen or last_seen < now - presence_timeout`
   (ICP, по умолчанию 120 с). Присутствие проверяется **на момент крона**, а
   окно сообщений — за весь период, как требует §9.6 («дайджест уходит целиком
   за час, даже если гость отключился в середине»);
3. окно: `since = last_digest_sent or (now - интервал крона)`; считаем
   сообщения по домену А3 с `date > since` и `author_id != partner_id`;
   ноль — пропускаем;
4. ссылка: `is_link_consumed` → `_streams_issue_link()` (ротация, Р12), иначе
   текущая ссылка;
5. письмо: `streams.mail_template_guest_digest.send_mail(participant.id,
   force_send=False, email_values={...})` — `force_send=False`, отправку доедет
   ядровый крон почты; в `email_values` те же `reply_to` / `references` /
   `headers`, что и в приглашении (А6.3);
6. `last_digest_sent = now`;
7. commit по каждому участнику не нужен, но исключение по одному участнику не
   должно ронять весь крон: `try/except` + `_logger.exception`.

Шаблон письма (модель `mail.channel.external.participant`,
`lang = {{ object.partner_id.lang }}`), без содержимого переписки:

```
Subject: New messages in the chat about {{ object.channel_id.name }}
Body:    Hello {{ object.partner_id.name }},
         there are new messages in the chat about {{ object.channel_id.name }}.
         [Open the chat]  (ссылка)
         This link is personal, please do not share it.
```

### А8. Ответ гостя по email (§9.7)

Отдельного кода почти нет — работает ядро, но у него есть предусловия, которые
мы обязаны обеспечить и проверить тестом:

- у участника есть `anchor_message_id`, и это сообщение **не** internal-подтипа
  (Р10) — иначе ответ приедет заметкой (`mail_thread.py:1502-1505`);
- каждое письмо гостю несёт `References` (и `In-Reply-To`) с
  `anchor.message_id` — по нему `message_route` найдёт `(model, res_id)`
  (`mail_thread.py:890-899`);
- `reply_to` — результат `record._notify_get_reply_to(default=...)[record.id]`
  (`models.py:96-172`); если он пустой (нет `mail.catchall.domain`), при
  приглашении пишем `_logger.warning` «guest replies cannot be routed» —
  админ должен знать.

Дальше: Mailgun-вебхук (`mailgun/controllers/main.py:10-24`) → `message_process`
→ `_message_route_process` (`mail_thread.py:1049-1080`) постит на запись с
`message_type='email'` и автором-контактом → наш классификатор даёт
`message` (`streams/models/mail_message.py:97`) → `_message_post_after_hook`
подшивает в канал → гость видит свой ответ на странице.

### А9. Настройки (§14)

`models/res_config_settings.py` (образец —
`transeu_bridge/models/res_config_settings.py:11-27`), все через
`config_parameter`:

| Поле | ICP | Умолчание |
|---|---|---|
| `streams_guest_session_days` | `streams.guest_session_days` | 7 |
| `streams_guest_poll_interval` | `streams.guest_poll_interval` | 10 (сек) |
| `streams_guest_edit_window` | `streams.guest_edit_window` | 120 (сек) |
| `streams_guest_presence_timeout` | `streams.guest_presence_timeout` | 120 (сек) |
| `streams_guest_max_upload_mb` | `streams.guest_max_upload_mb` | 25 |
| `streams_guest_digest_hours` | — | 1, пишется в `interval_number` крона в `set_values` / читается в `get_values` |

Все чтения — через хелпер `_streams_guest_param(key, default)` на модели
участника (`get_param` возвращает строку, `ir_config_parameter.py:60`), с
`int()` и защитой от мусора.

Вьюха настроек — блок `Streams — Guest access` с полями и одной подсказкой
про необходимость заполненного catchall.

### А10. Инварианты безопасности (сводка для ревью)

1. Гость не может прочитать ничего, кроме сообщений своего канала по домену А3:
   у контроллера физически нет другой точки входа в `mail.message`.
2. `note` / `change` / `activity` / «прочее» (включая якорь) гостю не отдаются
   никогда — тест на матрице подтипов.
3. Все ORM-операции гостя — `sudo` внутри узких методов; ни один параметр
   запроса не попадает в `browse()` без проверки принадлежности каналу.
4. Секреты сравниваются `consteq`, генерируются `secrets.token_urlsafe(32)`,
   в БД лежат под `groups='base.group_system'`.
5. Отзыв (`active=False`), архивация канала, истечение `session_expiry` —
   мгновенно и одинаково закрывают все маршруты (410).
6. Кука `httponly` + `SameSite=Lax` + `secure` на https, `path='/streams'`.
7. Тело от гостя — только plaintext через `plaintext2html`; вложения — с
   лимитом размера/количества.
8. `session_info` на публичную страницу не отдаётся; бэкенд-ассеты не
   подключаются.

### А11. Тесты (обязательные)

`tests/test_streams_guest.py` (`TransactionCase`, `post_install`), подопытная
модель — `res.partner`, как в существующих тестах:

1. **Приглашение**: создаёт участника с токеном, `history_from`,
   `is_link_consumed=False`, якорь-сообщение появилось и классифицируется как
   «прочее» (`_streams_classify() is False`); повторное приглашение того же
   партнёра обновляет ту же строку, дубля нет.
2. **Одноразовость**: `_streams_from_token` находит участника; после
   `_streams_open_session()` токен пуст, повторный поиск ничего не находит,
   `session_token` выдан, `is_link_consumed=True`.
3. **Сессия**: `_streams_from_session` принимает валидную куку, отклоняет
   чужой/битый токен, протухшую `session_expiry`, отозванного (`active=False`)
   участника и архивированный канал.
4. **Домен видимости**: канал с note / comment / message / change / activity /
   якорем — гостю отдаются только comment и message; сообщение с
   `date < history_from` не отдаётся; **отдельный тест сверяет домен с
   `_streams_classify_vals` по матрице (subtype × message_type)**.
5. **Пост гостя**: сообщение лежит на записи с `author_id = partner`,
   подтипом `streams.mt_message`, слинковано с каналом; `mail.mail` не создан;
   партнёр не стал ни follower'ом, ни `mail.channel.partner`.
6. **Правка**: в пределах окна тело меняется; за окном — отказ; чужое
   сообщение — отказ; заметку сотрудника гость править не может.
7. **Удаление**: тело пустеет, вложения отвязаны, строка `mail.message` жива,
   сообщение выпадает из гостевой ленты.
8. **Реакции**: создаётся `mail.message.reaction` с `partner_id` гостя; на
   невидимом сообщении (заметке) — отказ; повторная реакция идемпотентна.
9. **Вложения**: вложение видимого сообщения отдаётся, вложение заметки — 404,
   вложение чужого канала — 404.
10. **Дайджест**: отсутствующий гость с новыми сообщениями получает ровно одно
    письмо; присутствующий (`last_seen` свежий) — ноль; гость, у которого за час
    были только change/note — ноль; собственные сообщения гостя не считаются;
    `last_digest_sent` обновлён.
11. **Ротация**: у сожжённой ссылки токен меняется, старый перестаёт работать,
    `history_from`/`partner_id`/`anchor_message_id` сохранены, кука-сессия
    продолжает работать; у несожжённой (`is_link_consumed=False`) токен тот же.
12. **Письмо гостю уходит вопреки общему запрету**: `mail.mail` создан,
    `email_to == partner.email`, в `references` — `anchor.message_id`,
    `reply_to` непустой (в тесте выставить `mail.catchall.domain`/`alias`).
13. **Ответ по email**: скормить `message_process` сырое письмо с
    `References: <anchor.message_id>` от адреса контакта → сообщение легло на
    запись, `message_type='email'`, `author_id == partner`, классификация
    `message`, слинковано с каналом, видно в гостевой ленте.
14. **ACL**: чтение `mail.channel.external.participant` обычным внутренним
    пользователем даёт `AccessError`; `base.group_system` читает.
15. **Отзыв**: после `_streams_revoke()` ни один хелпер не находит участника ни
    по токену, ни по сессии.

---

## Б. UI

### Б1. Диалог приглашения (§9.2)

- Кнопка **`Invite customer`** в шапке канала записи — тот же приём, что и
  тумблеры фильтров: `t-inherit="mail.ThreadViewTopbar"` +
  `registerInstancePatchModel('mail.thread_view_topbar')`
  (`static/src/xml/thread_view_topbar.xml:4-21`,
  `static/src/models/thread_view_topbar.js:9-52`), показывать только при
  `thread.streamsChannelKind === 'record'`. Клик — `action.doAction` на
  `ir.actions.act_window` визарда с `default_channel_id`.
- Форма визарда: `partner_ids` (widget `many2many_tags`), `history_from`,
  `send_email`, алерт-предупреждение, ниже — список уже выданных доступов
  (партнёр, дата приглашения, `Last seen`, кнопка `Revoke`).
  После `action_invite` (`state='done'`) — список ссылок с
  `widget="CopyClipboardChar"` и текст `Copy the link and send it to the
  contact if they have no email.`
- В чаттере кнопку в этой фазе **не добавляем** (см. «Вопросы архитектору»):
  чаттер не знает, есть ли у записи канал, и ради этого пришлось бы вводить
  дополнительный RPC на каждую форму.

### Б2. Публичная страница

Шаблоны `views/guest_templates.xml`:

- `streams.guest_layout` — самодостаточный `<html>` (образец
  `discuss_public_templates.xml:3-35`, но **без** `session_info`): meta viewport,
  `<link rel="stylesheet" href="/streams/static/src/guest/guest.css"/>`,
  `<script src="/streams/static/src/guest/guest.js"></script>`, в
  `window.streamsGuest` — только `{pollInterval, editWindow, channelName}`.
- `streams.guest_confirm` — карточка: «You have been invited to the chat about
  <name>», кнопка `Enter chat` (form POST + csrf_token), строка «This link works
  only once».
- `streams.guest_chat` — шапка (имя канала + список участников), лента,
  композер (textarea + кнопка `Send` + вложения), футер-статус
  (`Connected` / `Reconnecting…`).
- `streams.guest_gone` — «This chat link is no longer active. Please contact
  your manager.» (HTTP 410).

`guest.js` — простой vanilla-скрипт (~200 строк, без сборки):

- поллинг `/streams/guest/feed` раз в `pollInterval` c `after_id`;
- пауза поллинга при `document.visibilityState === 'hidden'` и немедленный
  запрос при возврате — это и есть «heartbeat присутствия» (§9.5): скрытая
  вкладка перестаёт обновлять `last_seen`, и гость честно считается
  отсутствующим;
- экспоненциальный backoff при сетевых ошибках, остановка навсегда при
  `{'error': 'gone'}` с показом текста из `streams.guest_gone`;
- у своих сообщений кнопки `Edit` / `Delete` рисуются, пока
  `editable_until > now`, и исчезают по таймеру локально (сервер всё равно
  перепроверяет);
- реакции — фиксированная палитра эмодзи, клик по своей реакции снимает её;
- отправка `Enter` / перевод строки `Shift+Enter`; оптимистичного рендера нет —
  после ответа сервера просто дозапрашиваем ленту (проще и не расходится).

Стиль страницы — свой минимальный CSS, без Bootstrap, тёмный текст на светлом,
адаптив под мобильный (клиенту часто присылают ссылку в мессенджер).

### Б3. Что НЕ делать

- Не подключать OWL, `web.assets_*`, longpolling и `mail.guest` (§9.5 прямо
  запрещает возню с шиной).
- Не трогать `channel_info`, `_channel_seen`, unread-механику — внешний участник
  в них не участвует (Р1).
- Не делать «восстановление доступа» и «повторную отправку той же ссылки» —
  §9.3 это запрещает осознанно.
- Не добавлять гостю ничего, кроме перечисленного в §9.4: ни поиска, ни
  скачивания всей истории, ни списка других записей.

---

## В. Браузерный прогон (обязателен)

Среда ветки `worried-horse`, https://velesagro11.dev.oduist.com; пароль admin —
из контекста задачи (если его нет, `reset_admin_password` со свежим Hex16 по
правилам корневого AGENTS.md). Скриншоты фоновой вкладки на этой машине не
рисуются — проверять по DOM через `evaluate_script`. При 429 у
browser-rendering — `mcp__paseo__browser_*`.

1. Логин админом, открыть партнёра, написать `Comment` (канал создаётся), затем
   `Note` (гость её видеть не должен).
2. Discuss → канал записи → кнопка `Invite customer`, выбрать контакт с email,
   `Show history from` = сейчас минус час, галочка письма включена → `Invite`.
   Проверить, что ссылка показана и копируется.
3. **Открыть ссылку в чистом контексте без логина** (новая вкладка/инкогнито;
   убедиться, что куки `session_id` бэкенда нет): видна страница подтверждения,
   лента не видна. Нажать `Enter chat` → редирект на `/streams/guest/chat`,
   лента показывает comment, **не** показывает note.
4. Повторно открыть исходную ссылку — 404 (одноразовость).
5. Гость пишет сообщение с вложением → в Odoo (вкладка сотрудника) сообщение
   появилось и в чаттере записи, и в канале, автор — контакт; вложение
   скачивается у гостя по своей ссылке.
6. Сотрудник пишет comment → у гостя он появляется в течение ~10 с (поллинг).
7. Гость правит своё сообщение, затем удаляет его → у сотрудника сообщение
   исчезает из ленты; через `run_odoo_shell` сдвинуть `date` сообщения на 10
   минут назад → кнопки правки/удаления у гостя больше не действуют (сервер
   отвечает ошибкой).
8. Отозвать доступ в визарде → страница гостя при следующем поллинге показывает
   «no longer active», перезагрузка даёт 410.
9. Консоль гостевой страницы без ошибок; в HTML страницы нет `__session_info__`
   и нет бэкенд-бандлов (проверить `evaluate_script`-ом по `document.documentElement.outerHTML`).
10. Дайджест: `run_odoo_shell` — выставить `last_seen` в прошлое, вызвать
    `_cron_streams_guest_digest()`, проверить созданный `mail.mail`
    (email_to, references, отсутствие текста переписки) и новый токен.

---

## Процесс

Как в фазах 1a/1b/2: правка → commit/push (`Co-Authored-By: Claude Fable 5
<noreply@anthropic.com>`) → сразу
`pull_and_apply(env_name="worried-horse", upgrade="streams")` (новая модель,
данные, шаблоны, крон, вьюхи — только `-u`, не `restart`) → читать ошибки прямо
в ответе → `run_odoo_tests(modules="streams")`: все существующие сценарии
(23 из фазы 1 + сценарии фазы 2, если она к тому моменту влита) плюс новые
должны быть зелёными. Бамп версии `streams` минорный (следующий после фазы 2).
Известный шум прод-шаблона про `mcp_server` игнорировать.

Новые файлы модуля:

```
models/mail_channel_external_participant.py
models/mail_thread.py              (+ override _check_can_update_message_content)
models/res_config_settings.py
wizards/streams_guest_invite_wizard.py
controllers/guest.py
data/ir_cron_data.xml
data/mail_template_data.xml
views/guest_templates.xml
views/streams_guest_invite_wizard_views.xml
views/res_config_settings_views.xml
static/src/guest/guest.css
static/src/guest/guest.js
static/src/models/thread_view_topbar.js  (правка: кнопка Invite)
static/src/xml/thread_view_topbar.xml    (правка)
tests/test_streams_guest.py
```

Гостевые `guest.css` / `guest.js` в `assets` манифеста **не** объявляются — они
отдаются как обычная статика по `/streams/static/...`.

По завершении обновить `docs/roadmap.md`: раздел «Сделано» (Фаза 4), отступления
от ТЗ и отметки в «To check / to do». Строки интерфейса — английские; переводы
`pl`/`ru` — стандартными `.po` в `i18n/` (гостевая страница переводится тем же
механизмом, потому что рендерится через `ir.ui.view` в языке `partner.lang`).

---

## Вопросы архитектору

1. **Ротация ссылки при непрочитанном приглашении.** §9.6 говорит «вместе с
   дайджестом выдаётся новая ссылка, старая инвалидируется». Буквальное чтение
   убивает ссылку в письме-приглашении, которое гость ещё не открыл (письмо
   пролежало час — ссылка мертва). Предлагаю ротировать только сожжённые ссылки
   (`is_link_consumed=True`), а несожжённую повторять в дайджесте как есть (Р12).
   Подтверждаешь?
2. **Кнопка приглашения в чаттере.** ТЗ говорит «из канала/чаттера». В канале
   Discuss всё дёшево. В чаттере кнопку нужно либо всегда показывать (и на
   записях без канала — тогда приглашение должно создавать канал, что ломает
   §5.1 «канал создаётся только сообщением»), либо тянуть в чаттер знание о
   наличии канала (лишний RPC на каждой форме). Делаем только в канале, или
   принимаем один из двух компромиссов?
3. **Список участников, который видит гость.** §9.4 требует «ФИО сотрудников как
   есть». Показывать ли гостю **других внешних участников** того же канала
   (например, второго контакта той же компании)? Предлагаю показывать с пометкой
   «external», чтобы гость понимал состав, но это раскрытие одного клиента
   другому.
4. **Семантика удаления.** Odoo 15 удаляет сообщение опустошением тела, строка
   остаётся, и сообщение пропадает из всех лент, включая чаттер сотрудников
   (Р7). Устраивает, или сотрудники должны видеть след «сообщение удалено
   клиентом»?
5. **Порог отсутствия для дайджеста.** ТЗ говорит «нет heartbeat», числа не даёт.
   Предлагаю `presence_timeout = 120 с` (2 интервала поллинга + запас) как
   настройку. Ок или нужно другое значение / вынести в §14 явным пунктом?
---

## Решения по развилкам (2026-08-18, архитектор + пользователь)

1. **Ротация ссылки** — только для сожжённых (`is_link_consumed=True`); несожжённая
   повторяется в дайджесте как есть (Р12 подтверждён).
2. **Кнопка Invite customer — и в канале, и в чаттере.** Приглашение из чаттера
   записи без канала СОЗДАЁТ канал сразу («пятый триггер» §5.1, поправка в
   roadmap). Канал «скрыт» естественным образом: его видят только участники, а
   участники = followers; приглашающий увидит его, когда подпишется (напишет
   комментарий) или будет подписан. Гостевая механика не меняется (participant
   всегда имеет channel_id). Отложенное создание «при ответе клиента» отклонено:
   усложняет гостевой фид (nullable channel_id) без выгоды.
3. **Список участников для гостя** — показывать ВСЕХ участников канала: и
   сотрудников (ФИО как есть), и других внешних участников с пометкой external.
4. **Удаление сообщения гостем — «в виде заметки»**: вместо опустошения тела
   сообщение переподтипляется в `mail.mt_note` с префиксом
   "Deleted by the customer:" перед исходным телом (и `message_type` остаётся).
   Эффект: гость его больше не видит (note не входит в гостевой домен §9.4),
   сотрудники видят содержимое в потоке Notes чаттера/канала — след и аудит
   сохраняются без новых сущностей. Вложения отвязываются от гостевой выдачи
   вместе с сообщением (перестают проходить домен А3). Тест на оба эффекта.
   Правка гостем в окне 2 минут — без изменений (ядровый _update_content).
5. **Порог отсутствия** — 120 с, настройка `streams.guest_presence_timeout`
   (как в А9).

6. **Подписка пригласившего при ответе клиента (решение пользователя).**
   Когда от гостя приходит ответ — через гостевую страницу ИЛИ по email
   (маршрутизация §9.7) — сотрудник, выдавший этому участнику доступ
   (`participant.invited_by_id`), автоматически подписывается на запись, если
   ещё не подписан (message_subscribe → зеркало сделает его участником канала,
   unread-счётчик доставит сигнал). Иначе пригласивший, который сам не писал в
   канал (приглашение из чаттера не подписывает), ответа не увидит вовсе.
   Детали: подписывается именно invited_by соответствующего участника (у разных
   гостей могут быть разные пригласившие); неактивный/уволенный invited_by
   пропускается с warning-логом. Точки: гостевой POST-контроллер после
   message_post и обработчик входящего email-ответа (хук по классификации
   message + активный participant канала с author_id=partner). Тест: приглашение
   из чаттера без подписки → ответ гостя → пригласивший стал follower/участником
   и его unread канала = 1.
