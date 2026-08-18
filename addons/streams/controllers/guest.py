# -*- encoding: utf-8 -*-
import json
import logging
import re
from datetime import timedelta

from werkzeug.exceptions import NotFound

from odoo import http, fields
from odoo.http import request

from odoo.addons.streams.models.mail_channel_external_participant import (
    GUEST_COOKIE_NAME,
    GUEST_COOKIE_PATH,
    GUEST_REACTIONS,
    MAX_GUEST_ATTACHMENTS,
)

_logger = logging.getLogger(__name__)

# Ссылки на бэкенд в теле сообщения: вложения переписываются на наш
# маршрут, остальное вырезается (Р9).
WEB_ATTACHMENT_RE = re.compile(r'/web/(?:image|content)/(\d+)(?:[^"\'\s>]*)')
WEB_ANY_RE = re.compile(r'(?:href|src)=["\']/web/[^"\']*["\']')

# Сколько сообщений отдаётся за один запрос ленты
FEED_LIMIT = 30


class StreamsGuestController(http.Controller):
    """Публичный чат внешнего участника (§9.5, А4).

    Свои маршруты, а не ядровые `/mail/*` (Р2): ядро пускает анонима
    исключительно как `mail.guest` и исключительно к сообщениям с
    `model='mail.channel'`, а наши сообщения лежат на записи.
    """

    # ------------------------------------------------------------
    # ХЕЛПЕРЫ
    # ------------------------------------------------------------

    def _streams_participant(self):
        """Участник по куке сессии или None."""
        cookie = request.httprequest.cookies.get(GUEST_COOKIE_NAME)
        participant = request.env[
            'mail.channel.external.participant'].sudo()._streams_from_session(
                cookie)
        return participant or None

    def _streams_set_lang(self, participant):
        """Страница рендерится на языке контакта (Р5)."""
        lang = participant.sudo().partner_id.lang or 'en_US'
        request.context = dict(request.context, lang=lang)

    def _streams_set_cookie(self, response, participant):
        request_secure = request.httprequest.is_secure
        max_age = request.env[
            'mail.channel.external.participant']._streams_session_days() * 86400
        response.set_cookie(
            GUEST_COOKIE_NAME, participant._streams_cookie_value(),
            max_age=max_age, httponly=True, samesite='Lax',
            secure=request_secure, path=GUEST_COOKIE_PATH)
        return response

    def _streams_gone_page(self):
        """410 Gone: отозванный доступ, протухшая сессия, мёртвый канал."""
        response = request.render('streams.guest_gone', {})
        response.status_code = 410
        return response

    def _streams_gone_json(self):
        return {'error': 'gone'}

    def _streams_chat_context(self, participant):
        participant_sudo = participant.sudo()
        model = request.env['mail.channel.external.participant']
        return {
            'channel_name': participant_sudo.channel_id.name or '',
            'config': json.dumps({
                'pollInterval': model._streams_poll_interval(),
                'editWindow': model._streams_edit_window(),
                'channelName': participant_sudo.channel_id.name or '',
                'guestName': participant_sudo.partner_id.display_name or '',
                'reactions': list(GUEST_REACTIONS),
            }),
        }

    # ------------------------------------------------------------
    # ВИДИМОСТЬ И СЕРИАЛИЗАЦИЯ
    # ------------------------------------------------------------

    def _streams_render_body(self, body, allowed_attachment_ids):
        """Переписать бэкенд-ссылки тела на гостевые (Р9).

        Вставленные в тело картинки живут как `/web/image/<id>`; без
        подмены у гостя вместо них были бы битые иконки. Всё остальное
        `/web/...` вырезается: внутренние ссылки гостю бесполезны и
        говорят лишнего.
        """
        if not body:
            return ''
        body = str(body)

        def _replace(match):
            attachment_id = int(match.group(1))
            if attachment_id in allowed_attachment_ids:
                return '/streams/guest/attachment/%s' % attachment_id
            return '#'

        body = WEB_ATTACHMENT_RE.sub(_replace, body)
        body = WEB_ANY_RE.sub('href="#"', body)
        return body

    def _streams_message_values(self, participant, messages):
        participant_sudo = participant.sudo()
        partner = participant_sudo.partner_id
        window = request.env[
            'mail.channel.external.participant']._streams_edit_window()
        values = []
        for message in messages:
            attachments = message.attachment_ids
            allowed_ids = set(attachments.ids)
            is_own = message.author_id == partner
            editable_until = False
            if is_own and message.date:
                editable_until = fields.Datetime.to_string(
                    message.date + timedelta(seconds=window))
            reactions = {}
            for reaction in message.reaction_ids:
                bucket = reactions.setdefault(
                    reaction.content, {'content': reaction.content,
                                       'count': 0, 'mine': False})
                bucket['count'] += 1
                if reaction.partner_id == partner:
                    bucket['mine'] = True
            values.append({
                'id': message.id,
                'date': fields.Datetime.to_string(message.date),
                'author': message.author_id.display_name
                or message.email_from or '',
                'is_own': is_own,
                'body': self._streams_render_body(message.body, allowed_ids),
                'attachments': [
                    {
                        'id': attachment.id,
                        'name': attachment.name,
                        'mimetype': attachment.mimetype,
                    }
                    for attachment in attachments
                ],
                'reactions': list(reactions.values()),
                'editable_until': editable_until,
            })
        return values

    def _streams_feed_payload(self, participant, after_id=None,
                              before_id=None, limit=FEED_LIMIT):
        messages = participant._streams_visible_messages(
            after_id=after_id, before_id=before_id, limit=limit)
        participant_sudo = participant.sudo()
        return {
            'channel': {'name': participant_sudo.channel_id.name or ''},
            'me': {
                'partner_id': participant_sudo.partner_id.id,
                'name': participant_sudo.partner_id.display_name,
            },
            'members': participant._streams_members(),
            'messages': self._streams_message_values(participant, messages),
            'has_more': len(messages) >= limit,
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
        }

    # ------------------------------------------------------------
    # ССЫЛКА И СЕССИЯ
    # ------------------------------------------------------------

    @http.route('/streams/guest/<string:token>', type='http', auth='public',
                methods=['GET'], website=False, sitemap=False)
    def streams_guest_confirm(self, token, **kwargs):
        """Страница подтверждения. Ссылку GET **не** гасит (§9.3, Р4).

        Корпоративные антифишинг-сканеры прокликивают ссылки в письмах
        автоматически; сжигать токен на GET означало бы, что клиент до
        чата не доберётся.
        """
        participant = request.env[
            'mail.channel.external.participant'].sudo()._streams_from_token(
                token)
        if not participant:
            _logger.warning(
                'streams: неизвестный или сожжённый гостевой токен с адреса %s',
                request.httprequest.remote_addr)
            raise NotFound()
        self._streams_set_lang(participant)
        return request.render('streams.guest_confirm', {
            'channel_name': participant.sudo().channel_id.name or '',
            'company_name': request.env.company.name,
            'token': token,
        })

    @http.route('/streams/guest/<string:token>', type='http', auth='public',
                methods=['POST'], website=False, sitemap=False)
    def streams_guest_enter(self, token, **kwargs):
        """Осознанный вход: ссылка обменивается на сессию (§9.3).

        CSRF проверяет ядро (`http.py:785-819`); кука `session_id`
        поставлена на GET-ответе, поэтому `save_session=False` здесь
        ставить нельзя — иначе токен CSRF перестанет сходиться.
        """
        participant = request.env[
            'mail.channel.external.participant'].sudo()._streams_from_token(
                token)
        if not participant:
            _logger.warning(
                'streams: попытка входа по недействительному токену с адреса %s',
                request.httprequest.remote_addr)
            raise NotFound()
        participant._streams_open_session()
        response = request.redirect('/streams/guest/chat', code=303)
        return self._streams_set_cookie(response, participant)

    @http.route('/streams/guest/chat', type='http', auth='public',
                methods=['GET'], website=False, sitemap=False)
    def streams_guest_chat(self, **kwargs):
        """Страница чата. Сессия продлевается, кука переставляется."""
        participant = self._streams_participant()
        if not participant:
            return self._streams_gone_page()
        participant._streams_touch()
        self._streams_set_lang(participant)
        values = self._streams_chat_context(participant)
        values['feed'] = json.dumps(self._streams_feed_payload(participant))
        response = request.render('streams.guest_chat', values)
        return self._streams_set_cookie(response, participant)

    # ------------------------------------------------------------
    # ЛЕНТА
    # ------------------------------------------------------------

    @http.route('/streams/guest/feed', type='json', auth='public',
                methods=['POST'])
    def streams_guest_feed(self, after_id=None, before_id=None,
                           limit=FEED_LIMIT, **kwargs):
        participant = self._streams_participant()
        if not participant:
            return self._streams_gone_json()
        participant._streams_touch()
        try:
            limit = min(int(limit or FEED_LIMIT), 100)
        except (TypeError, ValueError):
            limit = FEED_LIMIT
        return self._streams_feed_payload(
            participant, after_id=after_id, before_id=before_id, limit=limit)

    # ------------------------------------------------------------
    # ОТПРАВКА, ПРАВКА, УДАЛЕНИЕ
    # ------------------------------------------------------------

    @http.route('/streams/guest/post', type='json', auth='public',
                methods=['POST'])
    def streams_guest_post(self, body='', attachment_ids=None, **kwargs):
        """Сообщение гостя ложится на саму запись (§9.4, А5)."""
        participant = self._streams_participant()
        if not participant:
            return self._streams_gone_json()
        participant._streams_touch()
        message, error = participant._streams_post_message(
            body,
            attachment_ids=self._streams_own_attachments(
                participant, attachment_ids))
        if error:
            return {'error': error}
        return {'ok': True, 'message_id': message.id}

    def _streams_own_attachments(self, participant, attachment_ids):
        """Только pending-вложения, загруженные ЭТИМ участником.

        Все гости работают под публичным uid, поэтому принадлежность
        определяется маркером участника в `res_id` (см. upload).
        """
        if not attachment_ids:
            return []
        try:
            ids = [int(item) for item in attachment_ids][:MAX_GUEST_ATTACHMENTS]
        except (TypeError, ValueError):
            return []
        attachments = request.env['ir.attachment'].sudo().browse(ids).exists()
        return attachments.filtered(
            lambda attachment: attachment.res_model == 'mail.compose.message'
            and attachment.res_id == participant.id).ids

    @http.route('/streams/guest/update', type='json', auth='public',
                methods=['POST'])
    def streams_guest_update(self, message_id=None, body='', **kwargs):
        """Правка своего сообщения в окне (§9.4)."""
        participant = self._streams_participant()
        if not participant:
            return self._streams_gone_json()
        participant._streams_touch()
        dummy, error = participant._streams_update_message(message_id, body)
        if error:
            return {'error': error}
        return {'ok': True}

    @http.route('/streams/guest/delete', type='json', auth='public',
                methods=['POST'])
    def streams_guest_delete(self, message_id=None, **kwargs):
        """Удаление гостем = сообщение становится заметкой (решение 4).

        Тело не опустошается: сообщение переподтипливается в
        `mail.mt_note` с префиксом. Гость его больше не видит (note не
        входит в гостевой домен §9.4), сотрудники видят содержимое в
        потоке Notes — след и аудит сохраняются без новых сущностей.
        Вложения вместе с сообщением выпадают из гостевой выдачи.
        """
        participant = self._streams_participant()
        if not participant:
            return self._streams_gone_json()
        participant._streams_touch()
        dummy, error = participant._streams_delete_message(message_id)
        if error:
            return {'error': error}
        return {'ok': True}

    # ------------------------------------------------------------
    # РЕАКЦИИ
    # ------------------------------------------------------------

    @http.route('/streams/guest/reaction', type='json', auth='public',
                methods=['POST'])
    def streams_guest_reaction(self, message_id=None, content=None,
                               action='add', **kwargs):
        """Реакция гостя (Р8): партнёр настоящий, значит она неотличима."""
        participant = self._streams_participant()
        if not participant:
            return self._streams_gone_json()
        participant._streams_touch()
        done, error = participant._streams_toggle_reaction(
            message_id, content, add=(action != 'remove'))
        if error:
            return {'error': error}
        return {'ok': done}

    # ------------------------------------------------------------
    # ВЛОЖЕНИЯ
    # ------------------------------------------------------------

    @http.route('/streams/guest/upload', type='http', auth='public',
                methods=['POST'], csrf=False)
    def streams_guest_upload(self, ufile=None, **kwargs):
        participant = self._streams_participant()
        if not participant:
            return self._streams_json_response({'error': 'gone'}, status=410)
        participant._streams_touch()
        if not ufile:
            return self._streams_json_response({'error': 'empty'}, status=400)
        data = ufile.read()
        max_bytes = request.env[
            'mail.channel.external.participant']._streams_max_upload_bytes()
        if len(data) > max_bytes:
            return self._streams_json_response(
                {'error': 'too_large'}, status=400)
        name = (ufile.filename or 'file').replace('/', '_').replace(
            '\\', '_').strip()[:255] or 'file'
        attachment = request.env['ir.attachment'].sudo().create({
            'name': name,
            'raw': data,
            # как ядро (`discuss.py:249-255`): вложение висит в pending, а
            # `message_post` перепривяжет его к записи. Все гости работают
            # под одним публичным uid, поэтому владелец pending-вложения
            # помечается id участника в res_id — иначе гость А мог бы
            # прикрепить к своему сообщению свежую загрузку гостя Б.
            # Ядровая перепривязка проверяет только res_model и create_uid
            # (mail_thread.py:1731-1734), маркеру не мешает.
            'res_model': 'mail.compose.message',
            'res_id': participant.id,
        })
        attachment._post_add_create()
        return self._streams_json_response({
            'id': attachment.id,
            'name': attachment.name,
            'mimetype': attachment.mimetype,
            'size': attachment.file_size,
        })

    def _streams_json_response(self, payload, status=200):
        """`make_response` кода ответа не принимает — ставим его отдельно."""
        response = request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')])
        response.status_code = status
        return response

    @http.route('/streams/guest/attachment/<int:attachment_id>', type='http',
                auth='public', methods=['GET'], website=False, sitemap=False)
    def streams_guest_attachment(self, attachment_id, download=None, **kwargs):
        """Вложение отдаётся только с видимого гостю сообщения (Р9)."""
        participant = self._streams_participant()
        if not participant:
            raise NotFound()
        participant._streams_touch()
        if not participant._streams_attachment_message(attachment_id):
            _logger.warning(
                'streams: гость %s запросил недоступное вложение %s',
                participant.id, attachment_id)
            raise NotFound()
        return request.env['ir.http'].sudo()._get_content_common(
            res_id=attachment_id, download=download)
