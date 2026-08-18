# -*- encoding: utf-8 -*-
from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestStreamsUi(common.TransactionCase):
    """Серверный контракт клиентской части (фаза 1b)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tag = cls.env['res.partner.category'].create({
            'name': 'Streams UI Tag'})
        cls.country = cls.env.ref('base.pl')
        cls.internal_user = cls.env['res.users'].create({
            'name': 'Streams UI User',
            'login': 'streams.ui@example.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.internal_partner = cls.internal_user.partner_id
        cls.external_partner = cls._make_partner('Streams UI External')

    @classmethod
    def _make_partner(cls, name):
        return cls.env['res.partner'].create({
            'name': name,
            'country_id': cls.country.id,
            'category_id': [(6, 0, [cls.tag.id])],
            'email': '%s@example.com' % name.lower().replace(' ', '.'),
        })

    def _channel_of(self, record):
        return self.env['mail.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])

    def _start_discussion(self, name):
        partner = self._make_partner(name)
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        return partner, self._channel_of(partner)

    # ------------------------------------------------------------
    # ОБРАТНАЯ ПРОЕКЦИЯ (§11.2)
    # ------------------------------------------------------------

    def test_01_channel_post_lands_on_record(self):
        partner, channel = self._start_discussion('Streams UI Reverse')
        message = channel.with_user(self.env.user).message_post(
            body='From the channel', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.assertEqual(
            message.model, 'res.partner',
            'сообщение из канала записи пишется на саму запись')
        self.assertEqual(message.res_id, partner.id)
        self.assertIn(
            channel, message.sudo().stream_channel_ids,
            'сообщение связано с каналом записи')
        self.assertIn(
            message, partner.message_ids,
            'сообщение видно в чаттере записи')

    def test_02_plain_channel_post_stays_in_channel(self):
        channel = self.env['mail.channel'].create({
            'name': 'Streams UI Plain Channel',
            'channel_type': 'channel',
        })
        message = channel.message_post(
            body='Hello', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.assertEqual(
            message.model, 'mail.channel',
            'обычный канал остаётся хранилищем своих сообщений')
        self.assertEqual(message.res_id, channel.id)

    # ------------------------------------------------------------
    # ШУМ ЯДРА
    # ------------------------------------------------------------

    def test_03_add_members_posts_no_notification(self):
        partner, channel = self._start_discussion('Streams UI Invite')
        before = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'mail.channel'), ('res_id', '=', channel.id)])
        channel.sudo().add_members(partner_ids=self.internal_partner.ids)
        after = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'mail.channel'), ('res_id', '=', channel.id)])
        self.assertEqual(
            after, before,
            'канал записи не заводит служебных «invited/joined»')
        self.assertIn(
            self.internal_partner, channel.sudo().channel_partner_ids)

    # ------------------------------------------------------------
    # ВЫДАЧА КЛИЕНТУ И ФИЛЬТРЫ (§6, §11.3)
    # ------------------------------------------------------------

    def test_04_channel_info_exposes_record_and_filters(self):
        partner, channel = self._start_discussion('Streams UI Info')
        channel.sudo().add_members(partner_ids=self.env.user.partner_id.ids)
        info = channel.sudo().channel_info()[0]
        self.assertEqual(info['channel_kind'], 'record')
        self.assertEqual(info['res_model'], 'res.partner')
        self.assertEqual(info['res_id'], partner.id)
        self.assertEqual(info['streams_filters'], {
            'comment': True,
            'note': True,
            'message': True,
            'change': False,
            'activity': True,
        })

    def test_05_plain_channel_info_has_no_record(self):
        channel = self.env['mail.channel'].create({
            'name': 'Streams UI Plain Info',
            'channel_type': 'channel',
        })
        info = channel.sudo().channel_info()[0]
        self.assertFalse(info['channel_kind'])
        self.assertFalse(info['res_model'])
        self.assertFalse(info['res_id'])

    def test_06_filters_are_per_user_and_persistent(self):
        partner, channel = self._start_discussion('Streams UI Filters')
        channel.sudo().add_members(partner_ids=(
            self.env.user.partner_id | self.internal_partner).ids)

        stored = channel.streams_set_filters({'change': True, 'note': False})
        self.assertTrue(stored['change'])
        self.assertFalse(stored['note'])
        self.assertTrue(
            stored['comment'], 'нетронутые потоки остаются по умолчанию')

        self.assertEqual(
            channel.sudo().channel_info()[0]['streams_filters']['change'],
            True, 'фильтры переживают перечитывание канала')

        other_info = channel.with_user(self.internal_user).channel_info()[0]
        self.assertFalse(
            other_info['streams_filters']['change'],
            'фильтры другого участника не меняются')

    def test_07_unknown_filter_keys_are_ignored(self):
        partner, channel = self._start_discussion('Streams UI Bad Filters')
        channel.sudo().add_members(partner_ids=self.env.user.partner_id.ids)
        stored = channel.streams_set_filters({'nonsense': True})
        self.assertNotIn('nonsense', stored)

    # ------------------------------------------------------------
    # ФОРМАТ СООБЩЕНИЯ
    # ------------------------------------------------------------

    def test_08_message_format_carries_stream_keys(self):
        partner, channel = self._start_discussion('Streams UI Format')
        message = partner.message_ids[:1]
        payload = message.message_format()[0]
        self.assertEqual(payload['streams_kind'], 'comment')
        self.assertEqual(payload['stream_channel_ids'], channel.ids)

    # ------------------------------------------------------------
    # БАТЧ-ACL ПРИ РАССЫЛКЕ (§6)
    # ------------------------------------------------------------

    def test_09_broadcast_skips_partners_without_access(self):
        partner, channel = self._start_discussion('Streams UI Acl')
        partners = self.internal_partner | self.external_partner
        readable = partner._streams_readable_partners(partners)
        self.assertIn(
            self.internal_partner, readable,
            'внутренний пользователь запись читает')
        self.assertNotIn(
            self.external_partner, readable,
            'партнёр без внутреннего пользователя получателем не бывает')

        rule = self.env['ir.rule'].sudo().create({
            'name': 'Streams UI deny partner',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'domain_force': "[('id', '!=', %s)]" % partner.id,
            'groups': [(6, 0, [])],
            'perm_read': True,
            'perm_write': False,
            'perm_create': False,
            'perm_unlink': False,
        })
        try:
            denied = partner.sudo()._streams_readable_partners(partners)
            self.assertNotIn(
                self.internal_partner, denied,
                'ir.rule закрывает запись и для рассылки проекций')
        finally:
            rule.unlink()

    def test_10_compose_wizard_accepts_subtype_xmlid(self):
        partner = self._make_partner('Streams UI Compose')
        wizard = self.env['mail.compose.message'].with_context(
            default_model='res.partner',
            default_res_id=partner.id,
            default_subtype_xmlid='streams.mt_message',
        ).create({'body': 'External'})
        self.assertEqual(
            wizard.subtype_id, self.env.ref('streams.mt_message'),
            'полный композер принимает подтип по xmlid')
