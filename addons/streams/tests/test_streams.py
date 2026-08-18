# -*- encoding: utf-8 -*-
from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestStreams(common.TransactionCase):
    """Серверное ядро потоков. Подопытная модель — res.partner."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tag = cls.env['res.partner.category'].create({
            'name': 'Streams Test Tag'})
        cls.country = cls.env.ref('base.pl')
        cls.internal_user = cls.env['res.users'].create({
            'name': 'Streams Internal User',
            'login': 'streams.internal@example.com',
            # 19: groups_id переименовано в group_ids
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.internal_partner = cls.internal_user.partner_id
        cls.external_partner = cls._make_partner('Streams External')

    @classmethod
    def _make_partner(cls, name):
        return cls.env['res.partner'].create({
            'name': name,
            'country_id': cls.country.id,
            'category_id': [(6, 0, [cls.tag.id])],
            'email': '%s@example.com' % name.lower().replace(' ', '.'),
        })

    def _flush_tracking(self):
        """Трекинг в Odoo 19 отложен до precommit — без него сообщения нет."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _channel_of(self, record):
        return self.env['discuss.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])

    def _messages_of(self, record):
        return self.env['mail.message'].sudo().search([
            ('model', '=', record._name),
            ('res_id', '=', record.id),
        ])

    # 1
    def test_01_create_does_not_subscribe(self):
        partner = self._make_partner('Streams Create')
        self.assertFalse(
            partner.message_partner_ids,
            'создание записи не должно никого подписывать')
        self.assertFalse(
            self._channel_of(partner), 'создание записи не создаёт канал')

    # 2
    def test_02_tracked_write_makes_change_message_without_channel(self):
        partner = self._make_partner('Streams Tracked')
        self._flush_tracking()
        before = self._messages_of(partner)
        partner.write({'email': 'tracked.changed@example.com'})
        self._flush_tracking()
        new_messages = self._messages_of(partner) - before
        self.assertEqual(
            len(new_messages), 1,
            'изменения одного write схлопываются в одно сообщение')
        self.assertEqual(new_messages._streams_classify(), 'change')
        self.assertEqual(
            new_messages.subtype_id,
            self.env.ref('streams.mt_change'))
        self.assertFalse(
            self._channel_of(partner), 'изменения канал не создают')

    # 3
    def test_03_comment_creates_channel_with_history(self):
        partner = self._make_partner('Streams Comment')
        partner.write({'email': 'comment.changed@example.com'})
        self._flush_tracking()
        history = self._messages_of(partner)
        self.assertTrue(history, 'до комментария история уже не пуста')
        message = partner.message_post(
            body='Hello', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self._channel_of(partner)
        self.assertTrue(channel, 'комментарий заводит канал записи')
        self.assertEqual(channel.res_model, 'res.partner')
        self.assertEqual(channel.res_id, partner.id)
        self.assertEqual(channel.name, partner.display_name)
        linked = (history | message).sudo().mapped('stream_channel_ids')
        self.assertEqual(
            linked, channel,
            'вся прежняя история подшивается к каналу')
        # правило §5.3 (2026-08-18): автор комментария/сообщения подписывается
        # автоматически; автор заметки — нет
        self.assertEqual(
            partner.message_follower_ids.partner_id,
            self.env.user.partner_id,
            'автор комментария автоматически подписывается на запись')
        self.assertEqual(
            channel.sudo().channel_partner_ids,
            self.env.user.partner_id,
            'подписка автора зеркалится в участники канала')

        note_partner = self._make_partner('Streams Note Author')
        note_partner.message_post(
            body='Private note', message_type='comment',
            subtype_xmlid='mail.mt_note')
        self.assertFalse(
            note_partner.message_follower_ids,
            'автор заметки не подписывается (§5.3)')
        note_channel = self._channel_of(note_partner)
        self.assertTrue(note_channel, 'заметка заводит канал записи')
        self.assertFalse(
            note_channel.sudo().channel_partner_ids,
            'канал от заметки создаётся без участников')

    # 4
    def test_04_note_and_incoming_email_create_channel(self):
        note_partner = self._make_partner('Streams Note')
        note_partner.message_post(
            body='Internal note', message_type='comment',
            subtype_xmlid='mail.mt_note')
        self.assertTrue(
            self._channel_of(note_partner), 'заметка заводит канал')

        mail_partner = self._make_partner('Streams Mail')
        message = mail_partner.message_post(
            body='Incoming', message_type='email',
            subtype_xmlid='mail.mt_comment')
        self.assertEqual(message._streams_classify(), 'message')
        self.assertTrue(
            self._channel_of(mail_partner), 'внешнее письмо заводит канал')

    # 5
    def test_05_system_messages_do_not_create_channel(self):
        partner = self._make_partner('Streams System')
        partner.message_post(
            body='System notification', message_type='notification',
            subtype_xmlid='mail.mt_note')
        self.assertFalse(
            self._channel_of(partner),
            'системное уведомление канал не создаёт')
        partner._message_log(body='Plain log')
        self.assertFalse(
            self._channel_of(partner), 'авто-лог канал не создаёт')
        creation_log = self._messages_of(partner)[-1:]
        self.assertFalse(creation_log._streams_classify())

    # 6
    def test_06_follower_and_member_sync(self):
        partner = self._make_partner('Streams Sync')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self._channel_of(partner)

        partner.message_subscribe(partner_ids=self.internal_partner.ids)
        self.assertIn(
            self.internal_partner, channel.sudo().channel_partner_ids,
            'follower становится участником канала')

        # 19: _action_remove_members удалён из ядра — выход из канала это
        # unlink участника discuss.channel.member
        self.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', self.internal_partner.id),
        ]).unlink()
        self.assertNotIn(
            self.internal_partner, partner.message_partner_ids,
            'выход из канала снимает follower')

    # 7
    def test_07_only_internal_partners_can_follow(self):
        partner = self._make_partner('Streams Followers')
        partner.message_subscribe(partner_ids=self.external_partner.ids)
        self.assertNotIn(
            self.external_partner, partner.message_partner_ids,
            'партнёр без внутреннего пользователя подписан быть не может')
        partner.message_subscribe(partner_ids=self.internal_partner.ids)
        self.assertIn(
            self.internal_partner, partner.message_partner_ids,
            'явная подписка внутреннего пользователя работает')

    # 8
    def test_08_rename_record_renames_channel(self):
        partner = self._make_partner('Streams Rename')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self._channel_of(partner)
        partner.write({'name': 'Streams Renamed'})
        self.assertEqual(
            channel.sudo().name, partner.display_name,
            'имя канала следует за display_name записи')

    # 9
    def test_09_archive_syncs_channel(self):
        partner = self._make_partner('Streams Archive')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self._channel_of(partner)
        partner.write({'active': False})
        self.assertFalse(channel.sudo().active)
        partner.write({'active': True})
        self.assertTrue(channel.sudo().active)

        partner.write({'active': False})
        self.assertFalse(channel.sudo().active)
        partner.message_post(
            body='Still talking', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.assertTrue(
            channel.sudo().active,
            'новое сообщение реанимирует канал архивированной записи')

    # 10
    def test_10_no_email_for_internal_recipients(self):
        partner = self._make_partner('Streams Mailing')
        self.assertEqual(self.internal_user.notification_type, 'inbox')

        mails_before = self.env['mail.mail'].sudo().search_count([])
        partner.message_post(
            body='For internal', message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=self.internal_partner.ids, force_send=False)
        self.assertEqual(
            self.env['mail.mail'].sudo().search_count([]), mails_before,
            'внутреннему пользователю письмо не уходит')

        partner.message_post(
            body='For customer', message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=self.external_partner.ids, force_send=False)
        self.assertGreater(
            self.env['mail.mail'].sudo().search_count([]), mails_before,
            'внешнему контакту письмо уходит')

    # 11
    def test_11_unread_ignores_changes(self):
        partner = self._make_partner('Streams Unread')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self._channel_of(partner)
        partner.message_subscribe(partner_ids=self.internal_partner.ids)

        # 19: счётчик непрочитанного живёт на участнике канала
        member = self.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', self.internal_partner.id),
        ], limit=1).with_user(self.internal_user).sudo()
        member.invalidate_recordset(['message_unread_counter'])
        before = member.message_unread_counter

        partner.message_post(
            body='Second', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        member.invalidate_recordset(['message_unread_counter'])
        after_comment = member.message_unread_counter
        self.assertEqual(
            after_comment, before + 1,
            'комментарий инкрементит счётчик непрочитанного')

        partner.write({'email': 'unread.changed@example.com'})
        self._flush_tracking()
        member.invalidate_recordset(['message_unread_counter'])
        self.assertEqual(
            member.message_unread_counter, after_comment,
            'изменение полей на счётчик не влияет')

    # 12
    def test_12_activity_events_produce_messages(self):
        partner = self._make_partner('Streams Activity')
        activity_subtype = self.env.ref('streams.mt_activity')
        activity = self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get('res.partner').id,
            'res_id': partner.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'summary': 'Call the customer',
            'user_id': self.env.user.id,
        })
        created = self._messages_of(partner).filtered(
            lambda message: message.subtype_id == activity_subtype)
        self.assertEqual(
            len(created), 1, 'создание активности пишет одно сообщение')
        self.assertEqual(created.author_id, self.env.user.partner_id)
        self.assertEqual(created._streams_classify(), 'activity')
        self.assertTrue(
            self._channel_of(partner), 'активность заводит канал записи')

        activity._action_done(feedback='Done')
        done = self._messages_of(partner).filtered(
            lambda message: message.subtype_id == activity_subtype)
        self.assertEqual(
            len(done), 2, 'закрытие активности пишет ещё одно сообщение')

    # 13
    def test_13_blacklisted_models_have_no_channel(self):
        channel = self.env['discuss.channel'].create({
            'name': 'Streams Plain Channel',
            'channel_type': 'channel',
        })
        channel.message_post(
            body='Hello channel', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.assertFalse(
            self.env['discuss.channel'].sudo().with_context(
                active_test=False).search([
                    ('channel_kind', '=', 'record'),
                    ('res_model', '=', 'discuss.channel'),
                ]),
            'у канала не бывает канала записи')
        self.assertFalse(channel.channel_kind)

        if 'connect_messagebox.message' in self.env:
            self.assertFalse(
                self.env['connect_messagebox.message']._streams_channel_enabled(),
                'connect_messagebox.message в чёрном списке')
