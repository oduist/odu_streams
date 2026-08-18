# -*- encoding: utf-8 -*-
import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import common, tagged
from odoo.tools import mute_logger

from odoo.addons.streams.models.mail_channel_external_participant import (
    GUEST_COOKIE_SEPARATOR,
    GUEST_DELETED_PREFIX,
    GUEST_REACTIONS,
)


@tagged('post_install', '-at_install')
class TestStreamsGuest(common.TransactionCase):
    """Гостевой доступ клиентов (§9). Подопытная модель — res.partner."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.country = cls.env.ref('base.pl')
        cls.tag = cls.env['res.partner.category'].create({
            'name': 'Streams Guest Tag'})
        cls.manager = cls.env['res.users'].create({
            'name': 'Streams Guest Manager',
            'login': 'streams.guest.manager@example.com',
            # право записи на res.partner: подопытная модель тестов — контакт,
            # а в этой базе group_user на неё только чтение
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('base.group_partner_manager').id,
            ])],
        })
        cls.customer = cls._make_partner('Streams Guest Customer')
        cls.other_customer = cls._make_partner('Streams Guest Other')
        # ответ гостя по email маршрутизируется только при заполненном catchall
        cls.env['ir.config_parameter'].sudo().set_param(
            'mail.catchall.domain', 'example.com')
        cls.env['ir.config_parameter'].sudo().set_param(
            'mail.catchall.alias', 'catchall')

    @classmethod
    def _make_partner(cls, name):
        return cls.env['res.partner'].create({
            'name': name,
            'country_id': cls.country.id,
            'category_id': [(6, 0, [cls.tag.id])],
            'email': '%s@example.com' % name.lower().replace(' ', '.'),
        })

    # ------------------------------------------------------------
    # ФИКСТУРЫ
    # ------------------------------------------------------------

    def _record_with_channel(self, name='Streams Guest Record'):
        """Запись с уже созданным каналом (комментарий — триггер §5.1)."""
        record = self._make_partner(name)
        record.with_user(self.manager).message_post(
            body='First comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ], limit=1)
        return record, channel

    def _invite(self, record=None, channel=None, partner=None,
                history_from=None, send_email=False, user=None):
        """Пройти визард приглашения от лица сотрудника."""
        user = user or self.manager
        if channel is None and record is not None:
            channel = self.env['mail.channel'].sudo().with_context(
                active_test=False).search([
                    ('channel_kind', '=', 'record'),
                    ('res_model', '=', record._name),
                    ('res_id', '=', record.id),
                ], limit=1)
        context = {}
        if channel:
            context['default_channel_id'] = channel.id
        else:
            context['default_res_model'] = record._name
            context['default_res_id'] = record.id
        wizard = self.env['streams.guest.invite.wizard'].with_user(
            user).with_context(**context).create({})
        values = {'partner_ids': [(6, 0, [(partner or self.customer).id])],
                  'send_email': send_email}
        if history_from:
            values['history_from'] = history_from
        wizard.write(values)
        wizard.action_invite()
        return wizard

    def _participant_of(self, channel, partner=None):
        return self.env['mail.channel.external.participant'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', (partner or self.customer).id),
        ], limit=1)

    def _visible_ids(self, participant):
        return participant._streams_visible_messages(limit=100).ids

    # ------------------------------------------------------------
    # 1. ПРИГЛАШЕНИЕ
    # ------------------------------------------------------------

    def test_01_invite_creates_participant_and_anchor(self):
        record, channel = self._record_with_channel('Guest Invite')
        before = self.env['mail.message'].sudo().search([
            ('model', '=', record._name), ('res_id', '=', record.id)])
        wizard = self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        self.assertTrue(participant, 'приглашение создаёт участника')
        self.assertTrue(participant.token, 'участнику выдан токен')
        self.assertFalse(
            participant.is_link_consumed, 'свежая ссылка ещё не сожжена')
        self.assertTrue(participant.history_from)
        self.assertEqual(participant.invited_by_id, self.manager)
        self.assertEqual(
            len(wizard.link_ids), 1, 'в диалоге показана одна ссылка')
        self.assertIn('/streams/guest/', wizard.link_ids.url)

        anchor = participant.anchor_message_id
        self.assertTrue(anchor, 'якорь треда создан')
        self.assertIn(
            anchor, self.env['mail.message'].sudo().search([
                ('model', '=', record._name), ('res_id', '=', record.id)]))
        self.assertNotIn(anchor, before)
        self.assertFalse(
            anchor._streams_classify(),
            'якорь — «прочее»: канал не заводит и в потоки не входит')
        self.assertEqual(anchor.message_type, 'notification')
        self.assertFalse(
            anchor.subtype_id.internal,
            'подтип якоря не internal, иначе ответ приедет заметкой')

        # повторное приглашение обновляет ту же строку
        self._invite(record=record, channel=channel)
        participants = self.env[
            'mail.channel.external.participant'].sudo().search([
                ('channel_id', '=', channel.id),
                ('partner_id', '=', self.customer.id)])
        self.assertEqual(len(participants), 1, 'дубля участника нет')

    def test_01b_invite_from_chatter_creates_channel(self):
        """Пятый триггер §5.1 (решение 2 от 2026-08-18)."""
        record = self._make_partner('Guest Invite No Channel')
        self.assertFalse(self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id)]))
        wizard = self._invite(record=record)
        channel = wizard.channel_id
        self.assertTrue(channel, 'приглашение из чаттера создаёт канал')
        self.assertEqual(channel.channel_kind, 'record')
        self.assertEqual(channel.res_id, record.id)
        self.assertFalse(
            record.message_follower_ids,
            'приглашение никого не подписывает')

    # ------------------------------------------------------------
    # 2. ОДНОРАЗОВОСТЬ ССЫЛКИ
    # ------------------------------------------------------------

    def test_02_link_is_single_use(self):
        record, channel = self._record_with_channel('Guest Single Use')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        token = participant.token
        model = self.env['mail.channel.external.participant']
        self.assertEqual(model._streams_from_token(token), participant)

        cookie = participant._streams_open_session()
        self.assertFalse(participant.token, 'ссылка гасится физически')
        self.assertTrue(participant.is_link_consumed)
        self.assertTrue(participant.session_token)
        self.assertTrue(participant.session_expiry)
        self.assertFalse(
            model._streams_from_token(token),
            'сожжённая ссылка больше не работает')
        self.assertEqual(
            cookie.split(GUEST_COOKIE_SEPARATOR)[0], str(participant.id))

    # ------------------------------------------------------------
    # 3. СЕССИЯ
    # ------------------------------------------------------------

    def test_03_session_lookup(self):
        record, channel = self._record_with_channel('Guest Session')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        cookie = participant._streams_open_session()
        model = self.env['mail.channel.external.participant']
        self.assertEqual(model._streams_from_session(cookie), participant)
        self.assertFalse(model._streams_from_session('garbage'))
        self.assertFalse(model._streams_from_session(
            '%s|wrong-token' % participant.id))
        self.assertFalse(model._streams_from_session('999999|x'))

        participant.session_expiry = fields.Datetime.now() - timedelta(days=1)
        self.assertFalse(
            model._streams_from_session(cookie), 'протухшая сессия не пускает')
        participant.session_expiry = fields.Datetime.now() + timedelta(days=1)
        self.assertTrue(model._streams_from_session(cookie))

        participant.active = False
        self.assertFalse(
            model._streams_from_session(cookie), 'отозванный не пускается')
        participant.active = True
        channel.sudo().active = False
        self.assertFalse(
            model._streams_from_session(cookie),
            'архивированный канал закрывает доступ')

    # ------------------------------------------------------------
    # 4. ДОМЕН ВИДИМОСТИ
    # ------------------------------------------------------------

    def test_04_visibility_domain(self):
        record, channel = self._record_with_channel('Guest Visibility')
        old_comment = record.with_user(self.manager).message_post(
            body='Old comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        # date хранится с точностью до секунды, поэтому старое сообщение
        # отодвигаем явно, а не полагаемся на «сейчас»
        old_comment.sudo().date = fields.Datetime.now() - timedelta(hours=2)
        participant.history_from = fields.Datetime.now() - timedelta(minutes=1)

        comment = record.with_user(self.manager).message_post(
            body='Visible comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        note = record.with_user(self.manager).message_post(
            body='Private note', message_type='comment',
            subtype_xmlid='mail.mt_note')
        message = record.with_user(self.manager).message_post(
            body='Customer message', message_type='comment',
            subtype_xmlid='streams.mt_message')
        change = record.sudo()._message_log(
            body='Change', tracking_value_ids=[])
        change.sudo().subtype_id = self.env.ref('streams.mt_change')
        activity = record.sudo().message_post(
            body='Activity', message_type='comment',
            subtype_xmlid='streams.mt_activity')
        anchor = participant.anchor_message_id

        visible = self._visible_ids(participant)
        self.assertIn(comment.id, visible)
        self.assertIn(message.id, visible)
        self.assertNotIn(note.id, visible, 'заметки гостю не видны')
        self.assertNotIn(change.id, visible, 'изменения гостю не видны')
        self.assertNotIn(activity.id, visible, 'активности гостю не видны')
        self.assertNotIn(anchor.id, visible, 'якорь гостю не виден')
        self.assertNotIn(
            old_comment.id, visible, 'история до history_from не видна')

    def test_04b_domain_matches_classifier(self):
        """Домен А3 обязан совпадать с классификатором на всей матрице."""
        record, channel = self._record_with_channel('Guest Matrix')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        participant.history_from = fields.Datetime.now() - timedelta(days=1)

        message_model = self.env['mail.message'].sudo()
        subtypes = message_model._streams_subtype_ids()
        subtype_ids = [False] + [
            subtypes[key] for key in sorted(subtypes) if subtypes.get(key)]
        message_types = [
            'comment', 'email', 'notification', 'user_notification']
        created = {}
        for subtype_id in subtype_ids:
            for message_type in message_types:
                message = message_model.create({
                    'model': record._name,
                    'res_id': record.id,
                    'body': 'matrix',
                    'subtype_id': subtype_id,
                    'message_type': message_type,
                    'author_id': self.manager.partner_id.id,
                    # сырое create мимо message_post: reply_to и record_name
                    # задаём сами, иначе ядро полезет их вычислять
                    'reply_to': 'catchall@example.com',
                    'record_name': record.display_name,
                })
                created[message.id] = (subtype_id, message_type)
        # user_notification к каналу не подшивается вовсе, остальное — да
        channel._streams_link_messages(message_model.browse(list(created)))

        visible = set(self._visible_ids(participant))
        for message_id, (subtype_id, message_type) in created.items():
            expected = message_model._streams_classify_vals(
                subtype_id, message_type) in ('comment', 'message')
            in_channel = bool(
                message_model.browse(message_id).stream_channel_ids)
            self.assertEqual(
                message_id in visible, expected and in_channel,
                'домен разошёлся с классификатором на (%s, %s)'
                % (subtype_id, message_type))

    # ------------------------------------------------------------
    # 5. ПОСТ ГОСТЯ
    # ------------------------------------------------------------

    def test_05_guest_post(self):
        record, channel = self._record_with_channel('Guest Post')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        mails_before = self.env['mail.mail'].sudo().search([])

        message, error = participant._streams_post_message('Hello from client')
        self.assertFalse(error)
        self.assertEqual(message.model, record._name)
        self.assertEqual(message.res_id, record.id)
        self.assertEqual(message.sudo().author_id, self.customer)
        self.assertEqual(
            message.sudo().subtype_id, self.env.ref('streams.mt_message'))
        self.assertEqual(message.sudo()._streams_classify(), 'message')
        self.assertIn(channel, message.sudo().stream_channel_ids)
        self.assertFalse(
            self.env['mail.mail'].sudo().search([]) - mails_before,
            'сообщение гостя писем не порождает')
        self.assertNotIn(
            self.customer, record.sudo().message_follower_ids.partner_id,
            'внешний контакт follower не становится')
        self.assertNotIn(
            self.customer, channel.sudo().channel_partner_ids,
            'внешний контакт участником канала не становится')
        self.assertIn(message.id, self._visible_ids(participant))

    # ------------------------------------------------------------
    # 6. ПРАВКА
    # ------------------------------------------------------------

    def test_06_guest_edit(self):
        record, channel = self._record_with_channel('Guest Edit')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        message, dummy = participant._streams_post_message('First version')

        edited, error = participant._streams_update_message(
            message.id, 'Second version')
        self.assertFalse(error)
        self.assertIn('Second version', edited.sudo().body)

        # чужое сообщение
        manager_message = record.with_user(self.manager).message_post(
            body='Manager comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        dummy, error = participant._streams_update_message(
            manager_message.id, 'Hijack')
        self.assertTrue(error, 'чужое сообщение править нельзя')

        # заметка сотрудника гостю не видна вовсе
        note = record.with_user(self.manager).message_post(
            body='Note', message_type='comment',
            subtype_xmlid='mail.mt_note')
        dummy, error = participant._streams_update_message(note.id, 'Hijack')
        self.assertTrue(error, 'невидимую заметку править нельзя')

        # за окном правки
        window = participant._streams_edit_window()
        message.sudo().date = fields.Datetime.now() - timedelta(
            seconds=window + 60)
        dummy, error = participant._streams_update_message(
            message.id, 'Too late')
        self.assertTrue(error, 'за окном правка запрещена')

    # ------------------------------------------------------------
    # 7. УДАЛЕНИЕ (решение 4 от 2026-08-18)
    # ------------------------------------------------------------

    def test_07_guest_delete_becomes_note(self):
        record, channel = self._record_with_channel('Guest Delete')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'guest.txt',
            'datas': base64.b64encode(b'hello'),
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        message, dummy = participant._streams_post_message(
            'Please delete me', attachment_ids=[attachment.id])
        self.assertIn(message.id, self._visible_ids(participant))
        self.assertTrue(participant._streams_attachment_message(attachment.id))

        deleted, error = participant._streams_delete_message(message.id)
        self.assertFalse(error)
        message = message.sudo()
        self.assertTrue(message.exists(), 'строка сообщения остаётся')
        self.assertEqual(
            message.subtype_id, self.env.ref('mail.mt_note'),
            'удаление гостем = переподтипливание в заметку')
        self.assertIn(GUEST_DELETED_PREFIX, message.body)
        self.assertIn(
            'Please delete me', message.body,
            'исходное тело сохраняется для аудита')
        self.assertEqual(message._streams_classify(), 'note')
        self.assertNotIn(
            message.id, self._visible_ids(participant),
            'удалённое гость больше не видит')
        self.assertFalse(
            participant._streams_attachment_message(attachment.id),
            'вложение выпадает из гостевой выдачи вместе с сообщением')

    # ------------------------------------------------------------
    # 8. РЕАКЦИИ
    # ------------------------------------------------------------

    def test_08_guest_reactions(self):
        record, channel = self._record_with_channel('Guest Reaction')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        message = record.with_user(self.manager).message_post(
            body='React to me', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        content = GUEST_REACTIONS[0]

        done, error = participant._streams_toggle_reaction(
            message.id, content, add=True)
        self.assertTrue(done)
        self.assertFalse(error)
        reactions = self.env['mail.message.reaction'].sudo().search([
            ('message_id', '=', message.id),
            ('partner_id', '=', self.customer.id)])
        self.assertEqual(len(reactions), 1)

        # повторная реакция идемпотентна
        participant._streams_toggle_reaction(message.id, content, add=True)
        self.assertEqual(len(self.env['mail.message.reaction'].sudo().search([
            ('message_id', '=', message.id),
            ('partner_id', '=', self.customer.id)])), 1)

        # снятие
        participant._streams_toggle_reaction(message.id, content, add=False)
        self.assertFalse(self.env['mail.message.reaction'].sudo().search([
            ('message_id', '=', message.id),
            ('partner_id', '=', self.customer.id)]))

        # на невидимом сообщении — отказ
        note = record.with_user(self.manager).message_post(
            body='Note', message_type='comment',
            subtype_xmlid='mail.mt_note')
        done, error = participant._streams_toggle_reaction(
            note.id, content, add=True)
        self.assertFalse(done)
        self.assertTrue(error)

        # произвольный эмодзи не принимается
        done, error = participant._streams_toggle_reaction(
            message.id, ':evil:', add=True)
        self.assertFalse(done)
        self.assertTrue(error)

    # ------------------------------------------------------------
    # 9. ВЛОЖЕНИЯ
    # ------------------------------------------------------------

    @mute_logger('odoo.addons.streams.models.mail_channel_external_participant')
    def test_09_attachment_access(self):
        record, channel = self._record_with_channel('Guest Attachment')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)

        visible_attachment = self.env['ir.attachment'].sudo().create({
            'name': 'visible.txt',
            'datas': base64.b64encode(b'visible'),
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        participant._streams_post_message(
            'With file', attachment_ids=[visible_attachment.id])
        self.assertTrue(
            participant._streams_attachment_message(visible_attachment.id))

        note_attachment = self.env['ir.attachment'].with_user(
            self.manager).create({
            'name': 'note.txt',
            'datas': base64.b64encode(b'note'),
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        record.with_user(self.manager).message_post(
            body='Internal note', message_type='comment',
            subtype_xmlid='mail.mt_note',
            attachment_ids=[note_attachment.id])
        self.assertFalse(
            participant._streams_attachment_message(note_attachment.id),
            'вложение заметки гостю недоступно')

        other_record, other_channel = self._record_with_channel(
            'Guest Attachment Other')
        other_attachment = self.env['ir.attachment'].with_user(
            self.manager).create({
            'name': 'other.txt',
            'datas': base64.b64encode(b'other'),
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        other_record.with_user(self.manager).message_post(
            body='Other channel', message_type='comment',
            subtype_xmlid='mail.mt_comment',
            attachment_ids=[other_attachment.id])
        self.assertFalse(
            participant._streams_attachment_message(other_attachment.id),
            'вложение чужого канала гостю недоступно')

    # ------------------------------------------------------------
    # 10. ДАЙДЖЕСТ
    # ------------------------------------------------------------

    def test_10_digest(self):
        record, channel = self._record_with_channel('Guest Digest')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        participant.write({
            'is_link_consumed': True,
            'last_seen': fields.Datetime.now() - timedelta(hours=2),
        })
        record.with_user(self.manager).message_post(
            body='New comment for the customer', message_type='comment',
            subtype_xmlid='mail.mt_comment')

        mails_before = self.env['mail.mail'].sudo().search([])
        self.env[
            'mail.channel.external.participant']._cron_streams_guest_digest()
        new_mails = self.env['mail.mail'].sudo().search([]) - mails_before
        digest = new_mails.filtered(
            lambda mail: self.customer.email in (mail.email_to or ''))
        self.assertEqual(len(digest), 1, 'отсутствующий гость получает письмо')
        self.assertTrue(participant.last_digest_sent)
        self.assertNotIn(
            'New comment for the customer', digest.body_html or '',
            'дайджест не содержит текста переписки')

        # присутствующий гость письма не получает
        participant.write({
            'last_seen': fields.Datetime.now(),
            'last_digest_sent': fields.Datetime.now() - timedelta(hours=2),
        })
        record.with_user(self.manager).message_post(
            body='One more comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        mails_before = self.env['mail.mail'].sudo().search([])
        self.env[
            'mail.channel.external.participant']._cron_streams_guest_digest()
        self.assertFalse(
            self.env['mail.mail'].sudo().search([]) - mails_before,
            'присутствующий гость дайджест не получает')

        # только заметки/изменения — письма нет
        participant.write({
            'last_seen': fields.Datetime.now() - timedelta(hours=2),
            'last_digest_sent': fields.Datetime.now(),
        })
        record.with_user(self.manager).message_post(
            body='Internal only', message_type='comment',
            subtype_xmlid='mail.mt_note')
        mails_before = self.env['mail.mail'].sudo().search([])
        self.env[
            'mail.channel.external.participant']._cron_streams_guest_digest()
        self.assertFalse(
            self.env['mail.mail'].sudo().search([]) - mails_before,
            'заметки дайджеста не порождают')

        # собственные сообщения гостя не считаются
        participant.write({'last_digest_sent': fields.Datetime.now()})
        participant._streams_post_message('My own message')
        mails_before = self.env['mail.mail'].sudo().search([])
        self.env[
            'mail.channel.external.participant']._cron_streams_guest_digest()
        self.assertFalse(
            self.env['mail.mail'].sudo().search([]) - mails_before,
            'собственные сообщения гостя дайджеста не вызывают')

    # ------------------------------------------------------------
    # 11. РОТАЦИЯ ССЫЛКИ (Р12)
    # ------------------------------------------------------------

    def test_11_link_rotation(self):
        record, channel = self._record_with_channel('Guest Rotation')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        fresh_token = participant.token
        history_from = participant.history_from
        anchor = participant.anchor_message_id

        # несожжённая ссылка в дайджесте повторяется как есть
        participant.write({'last_seen': fields.Datetime.now() - timedelta(
            hours=2)})
        record.with_user(self.manager).message_post(
            body='Ping', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.env[
            'mail.channel.external.participant']._cron_streams_guest_digest()
        self.assertEqual(
            participant.token, fresh_token,
            'неоткрытое приглашение ротацией не убивается')

        # сожжённая — меняется
        cookie = participant._streams_open_session()
        participant.write({
            'last_seen': fields.Datetime.now() - timedelta(hours=2),
            'last_digest_sent': False,
        })
        record.with_user(self.manager).message_post(
            body='Ping again', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.env[
            'mail.channel.external.participant']._cron_streams_guest_digest()
        self.assertTrue(participant.token, 'выдана новая ссылка')
        self.assertNotEqual(participant.token, fresh_token)
        self.assertEqual(participant.history_from, history_from)
        self.assertEqual(participant.partner_id, self.customer)
        self.assertEqual(participant.anchor_message_id, anchor)
        self.assertEqual(
            self.env['mail.channel.external.participant']
            ._streams_from_session(cookie), participant,
            'ротируется ссылка, а не сессия')

    # ------------------------------------------------------------
    # 12. ПИСЬМО ГОСТЮ ВОПРЕКИ ОБЩЕМУ ЗАПРЕТУ
    # ------------------------------------------------------------

    def test_12_invitation_email(self):
        record, channel = self._record_with_channel('Guest Invite Email')
        mails_before = self.env['mail.mail'].sudo().search([])
        self._invite(record=record, channel=channel, send_email=True)
        participant = self._participant_of(channel)
        new_mails = self.env['mail.mail'].sudo().search([]) - mails_before
        invite = new_mails.filtered(
            lambda mail: self.customer.email in (mail.email_to or ''))
        self.assertEqual(len(invite), 1, 'приглашение ушло письмом')
        self.assertEqual(invite.email_to, self.customer.email)
        self.assertEqual(
            invite.references, participant.anchor_message_id.message_id,
            'письмо несёт References якоря')
        self.assertTrue(invite.reply_to, 'reply_to заполнен')

    # ------------------------------------------------------------
    # 13. ОТВЕТ ПО EMAIL
    # ------------------------------------------------------------

    def test_13_email_reply(self):
        record, channel = self._record_with_channel('Guest Email Reply')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        anchor = participant.anchor_message_id
        self.assertTrue(anchor.message_id)

        raw = """Return-Path: <%(email)s>
From: %(name)s <%(email)s>
To: catchall@example.com
Subject: Re: chat
Message-Id: <guest-reply-1@example.com>
In-Reply-To: %(anchor)s
References: %(anchor)s
Content-Type: text/plain

Answer from the customer.
""" % {
            'email': self.customer.email,
            'name': self.customer.name,
            'anchor': anchor.message_id,
        }
        # message_process возвращает thread_id записи, а не id сообщения
        self.env['mail.thread'].sudo().message_process(None, raw)
        message = self.env['mail.message'].sudo().search([
            ('message_id', '=', '<guest-reply-1@example.com>')], limit=1)
        self.assertTrue(message, 'ответ гостя лёг сообщением')
        self.assertEqual(message.model, record._name)
        self.assertEqual(message.res_id, record.id)
        self.assertEqual(message.message_type, 'email')
        self.assertEqual(message.author_id, self.customer)
        self.assertEqual(message._streams_classify(), 'message')
        self.assertIn(channel, message.stream_channel_ids)
        self.assertIn(message.id, self._visible_ids(participant))

    # ------------------------------------------------------------
    # 14. ACL
    # ------------------------------------------------------------

    @mute_logger('odoo.addons.base.models.ir_model')
    def test_14_acl(self):
        record, channel = self._record_with_channel('Guest ACL')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        with self.assertRaises(AccessError):
            participant.with_user(self.manager).read(['partner_id'])
        admin = self.env.ref('base.user_admin')
        self.assertTrue(participant.with_user(admin).read(['partner_id']))

    # ------------------------------------------------------------
    # 15. ОТЗЫВ
    # ------------------------------------------------------------

    def test_15_revoke(self):
        record, channel = self._record_with_channel('Guest Revoke')
        self._invite(record=record, channel=channel)
        participant = self._participant_of(channel)
        token = participant.token
        cookie = participant._streams_open_session()
        model = self.env['mail.channel.external.participant']

        participant._streams_revoke()
        self.assertFalse(participant.active)
        self.assertFalse(participant.token)
        self.assertFalse(participant.session_token)
        self.assertFalse(model._streams_from_token(token))
        self.assertFalse(model._streams_from_session(cookie))

    # ------------------------------------------------------------
    # 15b. СПИСОК УЧАСТНИКОВ (решение 3 от 2026-08-18)
    # ------------------------------------------------------------

    def test_15b_members_list(self):
        record, channel = self._record_with_channel('Guest Members')
        self._invite(record=record, channel=channel)
        self._invite(record=record, channel=channel,
                     partner=self.other_customer)
        participant = self._participant_of(channel)
        cookie = participant._streams_open_session()
        # именно так участника достаёт контроллер: с active_test=False
        live = self.env[
            'mail.channel.external.participant']._streams_from_session(cookie)

        members = live._streams_members()
        self.assertIn(
            {'name': self.manager.partner_id.display_name,
             'is_external': False}, members,
            'сотрудники видны как есть (§9.4)')
        externals = [
            member['name'] for member in members if member['is_external']]
        self.assertIn(self.customer.display_name, externals)
        self.assertIn(
            self.other_customer.display_name, externals,
            'другие внешние участники видны с пометкой external')

        # отозванный доступ из списка исчезает
        self._participant_of(channel, self.other_customer)._streams_revoke()
        externals = [
            member['name'] for member in live._streams_members()
            if member['is_external']]
        self.assertNotIn(
            self.other_customer.display_name, externals,
            'отозванный участник в списке не остаётся')

    # ------------------------------------------------------------
    # 16. АВТОПОДПИСКА ПРИГЛАСИВШЕГО (решение 6 от 2026-08-18)
    # ------------------------------------------------------------

    def test_16_reply_subscribes_inviter(self):
        record = self._make_partner('Guest Inviter Subscribe')
        self._invite(record=record, user=self.manager)
        channel = self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id)], limit=1)
        participant = self._participant_of(channel)
        self.assertNotIn(
            self.manager.partner_id,
            record.sudo().message_follower_ids.partner_id,
            'приглашение само по себе не подписывает')

        participant._streams_post_message('Customer answer')
        self.assertIn(
            self.manager.partner_id,
            record.sudo().message_follower_ids.partner_id,
            'ответ гостя подписывает пригласившего')
        self.assertIn(
            self.manager.partner_id, channel.sudo().channel_partner_ids,
            'подписка зеркалится в участники канала')
        unread = channel.with_user(self.manager).message_unread_counter
        self.assertEqual(unread, 1, 'ответ гостя даёт непрочитанное')

    def test_16b_inactive_inviter_is_skipped(self):
        record = self._make_partner('Guest Inviter Inactive')
        inviter = self.env['res.users'].create({
            'name': 'Streams Guest Leaver',
            'login': 'streams.guest.leaver@example.com',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('base.group_partner_manager').id,
            ])],
        })
        self._invite(record=record, user=inviter)
        channel = self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id)], limit=1)
        participant = self._participant_of(channel)
        inviter.active = False
        message, error = participant._streams_post_message('Answer')
        self.assertFalse(error, 'уволенный пригласивший ответ не ломает')
        self.assertNotIn(
            inviter.partner_id,
            record.sudo().message_follower_ids.partner_id)

    # ------------------------------------------------------------
    # 17. ОГРАНИЧЕНИЯ МОДЕЛИ
    # ------------------------------------------------------------

    def test_17_constraints(self):
        record, channel = self._record_with_channel('Guest Constraints')
        model = self.env['mail.channel.external.participant'].sudo()
        company = self.env['res.partner'].create({
            'name': 'Streams Guest Company',
            'is_company': True,
            'country_id': self.country.id,
            'category_id': [(6, 0, [self.tag.id])],
        })
        with self.assertRaises(Exception):
            model.create({
                'channel_id': channel.id, 'partner_id': company.id})
        with self.assertRaises(Exception):
            model.create({
                'channel_id': channel.id,
                'partner_id': self.manager.partner_id.id})

    def test_18_invite_requires_partner(self):
        record, channel = self._record_with_channel('Guest No Partner')
        wizard = self.env['streams.guest.invite.wizard'].with_user(
            self.manager).with_context(
                default_channel_id=channel.id).create({})
        with self.assertRaises(UserError):
            wizard.action_invite()
