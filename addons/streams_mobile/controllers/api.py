# -*- encoding: utf-8 -*-
"""API v1 мобильного клиента (§3 design-phase6).

Каждый эндпоинт начинается с ``mobile_auth()``: дальше ``request.env``
работает правами пользователя, sudo используется только для служебных
чтений (собственное членство, bus-канал собственного партнёра,
метаданные вложений). Формат ответов — компактный JSON §3, даты — UTC
ISO 8601 (``fields.Datetime.to_string``), пагинация — ``before_id``/
``limit`` (limit зажимается в 1..100).

Ошибки: ``{'error': {'code', 'message'}}`` с кодами ``auth_failed``,
``access_denied``, ``not_found``, ``bad_request``.
"""
import functools
import json
import logging

from werkzeug.exceptions import NotFound

from odoo import fields, http
# сериализация bus-канала — ровно та же, что в ядре (`_sendone`):
# колонка `channel` хранит json_dump(channel_with_db(db, target))
from odoo.addons.bus.models.bus import channel_with_db, json_dump
from odoo.addons.streams.models.mail_message import STREAMS_FILTER_DEFAULTS
from odoo.exceptions import (
    AccessError, MissingError, UserError, ValidationError)
from odoo.http import request

from .auth import mobile_auth, mobile_error

_logger = logging.getLogger(__name__)

BASE = '/streams/mobile/v1'

DEFAULT_LIMIT = 30
MAX_LIMIT = 100
POLL_LIMIT = 100


def _clamp_limit(limit, default=DEFAULT_LIMIT):
    try:
        value = int(limit or default)
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), MAX_LIMIT)


def guarded(func):
    """ORM-исключения → машинные коды ошибок (§2.3 design-phase6).

    Порядок важен: AccessError и MissingError — подклассы UserError.
    TypeError/ValueError ловятся ради кривых параметров RPC (`int('x')`).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AccessError as error:
            return mobile_error('access_denied', str(error))
        except MissingError as error:
            return mobile_error('not_found', str(error))
        except (UserError, ValidationError) as error:
            return mobile_error('bad_request', str(error))
        except (TypeError, ValueError) as error:
            _logger.warning('streams_mobile: кривые параметры запроса: %s',
                            error)
            return mobile_error('bad_request', 'Invalid parameters')
    return wrapper


def _format_author(message):
    author = message.author_id
    if not author:
        return None
    return {'id': author.id, 'name': author.display_name or ''}


def _format_message(message):
    """Компактная форма сообщения (§3). `message` — recordset прав юзера.

    tracking отдаётся только для change-сообщений: `tracking_value_ids`
    закрыто группой system, поэтому значения читаются sudo, а видимость
    каждого поля решает `_filter_has_field_access` правами пользователя
    (поле с groups=, недоступной пользователю, отфильтруется). Реакции
    в ACL admin-only (как и в вебе, где их собирает Store) — сводка
    по сообщению, которое пользователь уже читает, служебная.
    """
    env = message.env
    kind = message._streams_classify()
    tracking = None
    if kind == 'change':
        values = message.sudo().tracking_value_ids._filter_has_field_access(
            env)
        tracking = [
            {
                'field': value.field_id.name,
                'label': value.field_id.field_description,
                'old': value._format_display_value(
                    value.field_id.ttype, new=False)[0],
                'new': value._format_display_value(
                    value.field_id.ttype, new=True)[0],
            }
            for value in values
        ]
    partner = env.user.partner_id
    grouped = {}
    for reaction in message.sudo().reaction_ids:
        bucket = grouped.setdefault(
            reaction.content, {'count': 0, 'me': False})
        bucket['count'] += 1
        if reaction.partner_id == partner:
            bucket['me'] = True
    return {
        'id': message.id,
        'body': message.body or '',
        'date': fields.Datetime.to_string(message.date),
        'kind': kind,
        'author': _format_author(message),
        'attachments': [
            {
                'id': attachment.id,
                'name': attachment.name,
                'mimetype': attachment.mimetype or '',
                'size': attachment.file_size,
            }
            for attachment in message.attachment_ids
        ],
        'tracking': tracking,
        'reactions': [
            {'content': content, 'count': bucket['count'], 'me': bucket['me']}
            for content, bucket in grouped.items()
        ],
        'parent_id': message.parent_id.id or None,
    }


class StreamsMobileApiController(http.Controller):

    # ------------------------------------------------------------
    # ХЕЛПЕРЫ ДОСТУПА
    # ------------------------------------------------------------

    def _channel_access(self, channel_id):
        """(channel_sudo, member_sudo, error) — общий гейт каналов.

        Доступ: участник канала, либо (для record-канала) право чтения
        записи-источника. sudo здесь — служебное чтение: метаданные
        канала и собственное членство; бизнес-проверка прав идёт
        `has_access('read')` реального пользователя.
        """
        empty = request.env['discuss.channel'].sudo()
        if not channel_id:
            return empty, None, mobile_error(
                'bad_request', 'channel_id required')
        channel = request.env['discuss.channel'].sudo().with_context(
            active_test=False).browse(int(channel_id)).exists()
        if not channel:
            return empty, None, mobile_error('not_found', 'Channel not found')
        member = request.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', request.env.user.partner_id.id),
        ], limit=1)
        if member:
            return channel, member, None
        if channel.channel_kind == 'record' and channel.res_model \
                and channel.res_model in request.env:
            record = request.env[channel.res_model].with_context(
                active_test=False).browse(channel.res_id).exists()
            if record and record.has_access('read'):
                return channel, None, None
        return empty, None, mobile_error(
            'access_denied', 'You have no access to this channel')

    # ------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------

    @http.route(BASE + '/init', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def init(self):
        device, error = mobile_auth()
        if error:
            return error
        user = request.env.user
        members = request.env['discuss.channel.member'].search([
            ('partner_id', '=', user.partner_id.id)])
        return {
            'user': {
                'id': user.id,
                'name': user.name,
                'partner_id': user.partner_id.id,
            },
            'notify': request.env['mail.notify']._streams_init_messaging(),
            'unread_total': sum(members.mapped('message_unread_counter')),
            'filters_defaults': dict(STREAMS_FILTER_DEFAULTS),
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
        }

    # ------------------------------------------------------------
    # КАНАЛЫ
    # ------------------------------------------------------------

    @http.route(BASE + '/channels', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def channels(self, kinds=None, search=None, limit=None, offset=0):
        device, error = mobile_auth()
        if error:
            return error
        limit = _clamp_limit(limit, default=MAX_LIMIT)
        offset = max(int(offset or 0), 0)
        kinds = [str(kind) for kind in kinds] if kinds else None
        search = (search or '').strip().lower()
        members = request.env['discuss.channel.member'].search([
            ('partner_id', '=', request.env.user.partner_id.id)])
        entries = []
        for member in members:
            channel = member.channel_id
            try:
                if not channel.active:
                    continue
                kind = channel.channel_kind or channel.channel_type
            except AccessError:
                # протухшее членство в канале, закрытом ядровыми правилами,
                # не должно ронять весь список
                continue
            if kinds and kind not in kinds:
                continue
            name = channel.display_name or channel.name or ''
            if search and search not in name.lower():
                continue
            last_message = None
            last = channel._get_last_messages()
            if last:
                try:
                    last_message = _format_message(last[:1])
                except AccessError:
                    # участник мог потерять право чтения записи-источника:
                    # тело последнего сообщения ему не отдаётся
                    last_message = None
            entries.append({
                'id': channel.id,
                'name': name,
                'kind': kind,
                'res_model': channel.res_model or None,
                'res_id': channel.res_id or None,
                'unread': member.message_unread_counter,
                'last_message': last_message,
                'members_count': channel.member_count,
            })
        entries.sort(
            key=lambda entry: (
                entry['last_message']['id'] if entry['last_message'] else 0,
                entry['id']),
            reverse=True)
        return {'channels': entries[offset:offset + limit]}

    # ------------------------------------------------------------
    # ЛЕНТА КАНАЛА
    # ------------------------------------------------------------

    @http.route(BASE + '/channel/messages', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def channel_messages(self, channel_id=None, before_id=None, limit=None):
        device, error = mobile_auth()
        if error:
            return error
        channel, member, error = self._channel_access(channel_id)
        if error:
            return error
        if channel.channel_kind == 'changes':
            # у личной ленты Changes собственный формат — /v1/changes/feed
            return mobile_error(
                'bad_request', 'Use /v1/changes/feed for the Changes stream')
        result = request.env['mail.message']._message_fetch(
            None, thread=channel,
            before=int(before_id) if before_id else None,
            limit=_clamp_limit(limit))
        # search внутри _message_fetch шёл правами пользователя: проекции
        # записей, которые ему читать нельзя, уже отфильтрованы ACL
        return {
            'messages': [
                _format_message(message)
                for message in result['messages'].with_env(request.env)
            ],
        }

    # ------------------------------------------------------------
    # ПУБЛИКАЦИЯ
    # ------------------------------------------------------------

    @http.route(BASE + '/channel/post', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def channel_post(self, channel_id=None, body=None, kind='comment',
                     attachment_ids=None, mentioned_partner_ids=None):
        device, error = mobile_auth()
        if error:
            return error
        if kind not in ('comment', 'note'):
            return mobile_error('bad_request', "kind must be comment or note")
        channel, member, error = self._channel_access(channel_id)
        if error:
            return error
        if channel.channel_kind in ('changes', 'notifications'):
            return mobile_error(
                'bad_request', 'Personal service channels are read-only')
        body = body or ''
        attachment_ids = [int(att) for att in (attachment_ids or [])]
        if not body.strip() and not attachment_ids:
            return mobile_error('bad_request', 'body or attachments required')
        # канал в env пользователя: reverse-post механика streams сама
        # переложит сообщение на запись и проверит право чтения
        message = request.env['discuss.channel'].browse(
            channel.id).message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment' if kind == 'comment'
                              else 'mail.mt_note',
                attachment_ids=attachment_ids,
                partner_ids=[
                    int(partner)
                    for partner in (mentioned_partner_ids or [])
                ])
        return _format_message(message.with_env(request.env))

    # ------------------------------------------------------------
    # ПРОЧТЕНИЕ И ФИЛЬТРЫ
    # ------------------------------------------------------------

    @http.route(BASE + '/channel/mark_read', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def channel_mark_read(self, channel_id=None, last_message_id=None):
        device, error = mobile_auth()
        if error:
            return error
        if not last_message_id:
            return mobile_error('bad_request', 'last_message_id required')
        member = request.env['discuss.channel.member'].search([
            ('channel_id', '=', int(channel_id or 0)),
            ('partner_id', '=', request.env.user.partner_id.id),
        ], limit=1)
        if not member:
            return mobile_error(
                'access_denied', 'You are not a member of this channel')
        member._mark_as_read(int(last_message_id))
        member.invalidate_recordset(['message_unread_counter'])
        return {'ok': True, 'unread': member.message_unread_counter}

    @http.route(BASE + '/channel/filters', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def channel_filters(self, channel_id=None, filters=None):
        device, error = mobile_auth()
        if error:
            return error
        channel, member, error = self._channel_access(channel_id)
        if error:
            return error
        if not member:
            # фильтры — персональная настройка участника
            return mobile_error(
                'access_denied', 'You are not a member of this channel')
        if filters is None:
            current = member._streams_get_filters()
        else:
            current = request.env['discuss.channel'].browse(
                channel.id).streams_set_filters(filters)
            if current is False:
                return mobile_error(
                    'access_denied', 'You are not a member of this channel')
        return {'channel_id': channel.id, 'filters': current}

    # ------------------------------------------------------------
    # ЛЕНТА CHANGES
    # ------------------------------------------------------------

    @http.route(BASE + '/changes/feed', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def changes_feed(self, before_id=None, limit=None):
        device, error = mobile_auth()
        if error:
            return error
        channel = request.env['discuss.channel']._streams_get_changes_channel(
            create=False)
        if not channel:
            return {'channel_id': None, 'items': []}
        # канал вернулся sudo-поиском — методу ленты нужен env пользователя,
        # он сам проверит владельца и права на записи-источники
        channel = request.env['discuss.channel'].browse(channel.id)
        return {
            'channel_id': channel.id,
            'items': channel.streams_changes_feed(
                limit=_clamp_limit(limit),
                before_id=int(before_id) if before_id else None),
        }

    # ------------------------------------------------------------
    # ПОДПИСКА НА ПОЛЯ
    # ------------------------------------------------------------

    @http.route(BASE + '/fields/subscription', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def fields_subscription(self, res_model=None, res_id=None,
                            field_ids=None):
        device, error = mobile_auth()
        if error:
            return error
        res_model = (res_model or '').strip()
        if not res_model or res_model not in request.env or not res_id:
            return mobile_error('not_found', 'Unknown record')
        record = request.env[res_model].with_context(
            active_test=False).browse(int(res_id)).exists()
        if not record:
            return mobile_error('not_found', 'Unknown record')
        if field_ids is None:
            return record.streams_get_field_subscription()
        return record.streams_set_field_subscription(
            [int(field_id) for field_id in field_ids])

    # ------------------------------------------------------------
    # NOTIFY (обёртки RPC фазы 3)
    # ------------------------------------------------------------

    @http.route(BASE + '/notify/feed', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def notify_feed(self, box='received', before_id=None, limit=None):
        device, error = mobile_auth()
        if error:
            return error
        return {
            'items': request.env['mail.notify'].streams_notify_feed(
                box='sent' if box == 'sent' else 'received',
                limit=_clamp_limit(limit),
                before_id=int(before_id) if before_id else None),
        }

    @http.route(BASE + '/notify/send', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def notify_send(self, body=None, user_ids=None, attachment_ids=None,
                    is_sticky=False, timeout=None, res_model=None,
                    res_id=None):
        device, error = mobile_auth()
        if error:
            return error
        vals = {
            'body': body or '',
            'user_ids': [int(user_id) for user_id in (user_ids or [])],
            'attachment_ids': [
                int(attachment_id)
                for attachment_id in (attachment_ids or [])
            ],
            'is_sticky': bool(is_sticky),
        }
        if timeout:
            vals['timeout'] = int(timeout)
        if res_model and res_id:
            vals['res_model'] = str(res_model)
            vals['res_id'] = int(res_id)
        return request.env['mail.notify'].streams_notify_send(vals)

    @http.route(BASE + '/notify/reply', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def notify_reply(self, parent_id=None, body=None, attachment_ids=None,
                     is_sticky=None, timeout=None):
        device, error = mobile_auth()
        if error:
            return error
        vals = {
            'body': body or '',
            'attachment_ids': [
                int(attachment_id)
                for attachment_id in (attachment_ids or [])
            ],
        }
        # sticky/timeout не передали — сервер унаследует их от родителя
        if is_sticky is not None:
            vals['is_sticky'] = bool(is_sticky)
        if timeout:
            vals['timeout'] = int(timeout)
        return request.env['mail.notify'].streams_notify_reply(
            int(parent_id or 0), vals)

    @http.route(BASE + '/notify/mark_read', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def notify_mark_read(self, notify_ids=None):
        device, error = mobile_auth()
        if error:
            return error
        return request.env['mail.notify'].streams_notify_mark_read(
            [int(notify_id) for notify_id in (notify_ids or [])])

    @http.route(BASE + '/notify/popup_shown', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def notify_popup_shown(self, notify_ids=None):
        device, error = mobile_auth()
        if error:
            return error
        request.env['mail.notify'].streams_notify_popup_shown(
            [int(notify_id) for notify_id in (notify_ids or [])])
        return {'ok': True}

    # ------------------------------------------------------------
    # POLL (замена longpolling)
    # ------------------------------------------------------------

    @http.route(BASE + '/poll', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    @guarded
    def poll(self, last_bus_id=0):
        device, error = mobile_auth()
        if error:
            return error
        last = int(last_bus_id or 0)
        partner = request.env.user.partner_id
        # sudo — служебное чтение bus.bus, жёстко отфильтрованное каналом
        # СОБСТВЕННОГО партнёра: чужие уведомления не выбрать в принципе
        channel_key = json_dump(
            channel_with_db(request.env.cr.dbname, partner))
        rows = request.env['bus.bus'].sudo().search_read(
            [('id', '>', last), ('channel', '=', channel_key)],
            ['message'], order='id asc', limit=POLL_LIMIT)
        notifications = []
        for row in rows:
            try:
                payload = json.loads(row['message'])
            except (TypeError, ValueError):
                continue
            notifications.append({
                'id': row['id'],
                'type': payload.get('type'),
                'payload': payload.get('payload'),
            })
        if len(rows) >= POLL_LIMIT:
            # страница полная — продолжать с последнего отданного id
            new_last = rows[-1]['id']
        else:
            new_last = request.env['bus.bus'].sudo()._bus_last_id()
        return {
            'last_bus_id': max(new_last, last),
            'notifications': notifications,
        }

    # ------------------------------------------------------------
    # ВЛОЖЕНИЯ
    # ------------------------------------------------------------

    @http.route(BASE + '/attachment/upload', type='http', auth='public',
                methods=['POST'], csrf=False)
    def attachment_upload(self, **kwargs):
        device, error = mobile_auth()
        if error:
            return request.make_json_response(error, status=401)
        upload = next(iter(request.httprequest.files.values()), None)
        if upload is None or not upload.filename:
            return request.make_json_response(
                mobile_error('bad_request', 'file required'), status=400)
        data = upload.read()
        # лимит размера — как у гостя (streams.guest_max_upload_mb)
        max_bytes = request.env[
            'mail.channel.external.participant']._streams_max_upload_bytes()
        if len(data) > max_bytes:
            return request.make_json_response(
                mobile_error('bad_request', 'file too large'), status=413)
        name = (upload.filename or 'file').replace('/', '_').replace(
            '\\', '_').strip()[:255] or 'file'
        # pending-паттерн композера (как ядровый /mail/attachment/upload с
        # is_pending): message_post перепривяжет вложение к записи. Создание
        # правами пользователя: владелец pending — его create_uid
        attachment = request.env['ir.attachment'].create({
            'name': name,
            'raw': data,
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        attachment._post_add_create()
        return request.make_json_response({
            'id': attachment.id,
            'name': attachment.name,
            'mimetype': attachment.mimetype or '',
            'size': attachment.file_size,
        })

    def _attachment_readable(self, attachment):
        """Право пользователя видеть вложение (метаданные — sudo).

        Вложение доступно, если пользователь читает запись-владельца
        (сообщение записи / уведомление) — либо это его собственное
        pending-вложение композера.
        """
        env = request.env
        res_model, res_id = attachment.res_model, attachment.res_id
        if res_model == 'mail.compose.message':
            return attachment.create_uid.id == env.uid
        if not res_model or res_model not in env or not res_id:
            return False
        record = env[res_model].with_context(
            active_test=False).browse(res_id).exists()
        if not record:
            return False
        try:
            record.check_access('read')
        except (AccessError, MissingError):
            return False
        return True

    @http.route(BASE + '/attachment/<int:attachment_id>', type='http',
                auth='public', methods=['GET'], csrf=False)
    def attachment_download(self, attachment_id, **kwargs):
        device, error = mobile_auth()
        if error:
            return request.make_json_response(error, status=401)
        attachment = request.env['ir.attachment'].sudo().browse(
            attachment_id).exists()
        if not attachment or not self._attachment_readable(attachment):
            # чужое вложение неотличимо от несуществующего
            raise NotFound()
        # sudo обязателен: права уже проверены выше, а ir.attachment
        # напрямую пользователь читать не обязан уметь
        return request.env['ir.binary']._get_stream_from(
            attachment.sudo()).get_response(as_attachment=True)
