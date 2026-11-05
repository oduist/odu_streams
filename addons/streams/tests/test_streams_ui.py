# -*- encoding: utf-8 -*-
from odoo.addons.mail.tools.discuss import Store
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
            # 19: groups_id переименовано в group_ids
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
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
        return self.env['discuss.channel'].sudo().with_context(
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

    def _store_channel(self, channel):
        """Данные канала в клиентской выдаче.

        19: `channel_info()` удалён — клиент получает данные через Store;
        персональные ключи (`streams_filters`) считаются для пользователя
        env, от чьего лица собирается Store.
        """
        data = Store().add(channel).get_result()['discuss.channel']
        return next(item for item in data if item['id'] == channel.id)

    def _flush_tracking(self):
        """Трекинг в Odoo 19 отложен до precommit — без него сообщения нет."""
        self.env.flush_all()
        self.env.cr.precommit.run()

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
        channel = self.env['discuss.channel'].create({
            'name': 'Streams UI Plain Channel',
            'channel_type': 'channel',
        })
        message = channel.message_post(
            body='Hello', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.assertEqual(
            message.model, 'discuss.channel',
            'обычный канал остаётся хранилищем своих сообщений')
        self.assertEqual(message.res_id, channel.id)

    # ------------------------------------------------------------
    # ШУМ ЯДРА
    # ------------------------------------------------------------

    def test_03_add_members_posts_no_notification(self):
        # 19: ядро само не постит joined/left для channel_type='channel' —
        # тест фиксирует это поведение как инвариант канала записи
        partner, channel = self._start_discussion('Streams UI Invite')
        before = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id)])
        channel.sudo().add_members(partner_ids=self.internal_partner.ids)
        after = self.env['mail.message'].sudo().search_count([
            ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id)])
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
        # 19: channel_info() удалён — данные канала берутся из Store
        info = self._store_channel(channel.sudo())
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
        channel = self.env['discuss.channel'].create({
            'name': 'Streams UI Plain Info',
            'channel_type': 'channel',
        })
        # 19: channel_info() удалён — данные канала берутся из Store
        info = self._store_channel(channel.sudo())
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
            self._store_channel(channel.sudo())['streams_filters']['change'],
            True, 'фильтры переживают перечитывание канала')

        # 19: персональная выдача — Store, собранный от лица участника
        other_info = self._store_channel(
            channel.with_user(self.internal_user))
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
        # 19: message_format() удалён — формат клиента собирается через Store
        data = Store().add(message).get_result()['mail.message']
        payload = next(item for item in data if item['id'] == message.id)
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
        # 19: default_subtype_xmlid принимает само ядро (наш override
        # композера удалён); default_res_id ядром запрещён — default_res_ids
        partner = self._make_partner('Streams UI Compose')
        wizard = self.env['mail.compose.message'].with_context(
            default_model='res.partner',
            default_res_ids=partner.ids,
            default_subtype_xmlid='streams.mt_message',
        ).create({'body': 'External'})
        self.assertEqual(
            wizard.subtype_id, self.env.ref('streams.mt_message'),
            'полный композер принимает подтип по xmlid')

    # ------------------------------------------------------------
    # СЕРВЕРНАЯ ФИЛЬТРАЦИЯ ЛЕНТЫ (§6, решение Р1 фазы 8)
    # ------------------------------------------------------------

    def _seed_streams(self, name):
        """Запись с каналом и по сообщению на каждый поток плюс «прочее»."""
        partner, channel = self._start_discussion(name)
        channel.sudo().add_members(
            partner_ids=self.env.user.partner_id.ids)
        partner.message_post(
            body='note', message_type='comment',
            subtype_xmlid='mail.mt_note')
        partner.message_post(
            body='external', message_type='comment',
            subtype_xmlid='streams.mt_message')
        partner.message_post(
            body='activity', message_type='notification',
            subtype_xmlid='streams.mt_activity')
        # письмо — внешняя переписка независимо от подтипа
        partner.message_post(
            body='incoming mail', message_type='email',
            subtype_xmlid='mail.mt_comment')
        # системный автолог без наших подтипов — поток change (§6,
        # решение пользователя 2026-08-20)
        partner.message_post(
            body='system log', message_type='notification',
            subtype_xmlid='mail.mt_note')
        # «прочее»: чужой подтип, посланный не автологом и не письмом —
        # ни в один поток не попадает и фильтрами не скрывается
        partner.message_post(
            body='foreign subtype', message_type='comment',
            subtype_xmlid='mail.mt_activities')
        # трекинг сравнивает значения от предыдущего precommit: без сброса
        # правка записи, созданной в этой же транзакции, изменением не станет
        self._flush_tracking()
        partner.write({'email': 'streams.filters.changed@example.com'})
        self._flush_tracking()
        return partner, channel

    def _feed_ids(self, channel):
        """Идентификаторы ленты канала в окружении самого канала."""
        result = channel.env['mail.message']._message_fetch(
            None, thread=channel, limit=100)
        return set(result['messages'].ids)

    def _by_stream(self, channel):
        """Сообщения канала, сгруппированные классификатором по потокам."""
        grouped = {}
        messages = self.env['mail.message'].sudo().search(
            channel._streams_message_domain())
        for message in messages:
            if message.message_type == 'user_notification':
                continue
            grouped.setdefault(message._streams_classify(), set()).add(
                message.id)
        return grouped

    def test_11_feed_domain_matches_classifier(self):
        """Выключенный поток убирает из ленты ровно свои сообщения.

        Домен `_streams_stream_domain` — зеркало классификатора, и это
        единственное место, где они могут разъехаться: домен работает в
        SQL, классификатор — построчно в Python. Проверяем их равенство на
        реальной ленте, а не на синтетической матрице.
        """
        partner, channel = self._seed_streams('Streams UI Feed Match')
        grouped = self._by_stream(channel)
        # в ленте должны быть все пять потоков и «прочее»
        self.assertLessEqual(
            {'comment', 'note', 'message', 'change', 'activity', False},
            set(grouped),
            'сид покрывает все потоки')
        everything = set()
        for ids in grouped.values():
            everything |= ids

        for stream in ('comment', 'note', 'message', 'change', 'activity'):
            channel.streams_set_filters(dict(
                {key: True for key in
                 ('comment', 'note', 'message', 'change', 'activity')},
                **{stream: False}))
            self.assertEqual(
                self._feed_ids(channel), everything - grouped[stream],
                'выключение потока %s убирает ровно его сообщения' % stream)

    def test_12_feed_hides_disabled_streams_by_default(self):
        """Дефолт: change скрыт, «прочее» видно всегда (§6)."""
        partner, channel = self._seed_streams('Streams UI Feed Default')
        grouped = self._by_stream(channel)
        feed = self._feed_ids(channel)
        self.assertFalse(
            feed & grouped['change'],
            'change по умолчанию выключен и в ленту не попадает')
        self.assertLessEqual(
            grouped[False], feed,
            'сообщения без потока («прочее») видны при любых фильтрах')
        self.assertLessEqual(grouped['comment'], feed)
        self.assertLessEqual(grouped['note'], feed)

        channel.streams_set_filters({'change': True})
        self.assertLessEqual(
            grouped['change'], self._feed_ids(channel),
            'включённый change возвращается в ленту')

    def test_12b_system_autolog_is_a_change(self):
        """Системный автолог прячется фильтром Changes (§6, 2026-08-20).

        До 2026-08-20 такие сообщения были «прочим» и висели в ленте при
        любых фильтрах — жалоба пользователя на «Lead/Opportunity created»
        в Discuss с выключенным Changes.
        """
        partner, channel = self._start_discussion('Streams UI Autolog')
        channel.sudo().add_members(partner_ids=self.env.user.partner_id.ids)
        autolog = partner.message_post(
            body='Lead/Opportunity created', message_type='notification',
            subtype_xmlid='mail.mt_note')
        self.assertEqual(autolog.sudo()._streams_classify(), 'change')
        self.assertIn(
            channel, autolog.sudo().stream_channel_ids,
            'автолог в канал записи всё равно проецируется')
        self.assertNotIn(
            autolog.id, self._feed_ids(channel),
            'при выключенном Changes автолога в ленте нет')

        channel.streams_set_filters({'change': True})
        self.assertIn(
            autolog.id, self._feed_ids(channel),
            'включённый Changes возвращает автолог')

    def test_13_unfiltered_context_disables_filtering(self):
        """`streams_unfiltered=True` отключает фильтр (контракт мобильного)."""
        partner, channel = self._seed_streams('Streams UI Feed Unfiltered')
        grouped = self._by_stream(channel)
        unfiltered = self._feed_ids(
            channel.with_context(streams_unfiltered=True))
        self.assertLessEqual(
            grouped['change'], unfiltered,
            'без фильтра лента отдаёт и выключенные потоки')

    def test_14_personal_channels_are_never_filtered(self):
        """Личные каналы фильтров не имеют — фильтруется только record."""
        channel = self.env['discuss.channel']._streams_get_changes_channel(
            self.env.user)
        partner = self._make_partner('Streams UI Feed Personal')
        self._flush_tracking()
        partner.write({'email': 'streams.personal.changed@example.com'})
        self._flush_tracking()
        message = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id),
            ('tracking_value_ids', '!=', False),
        ], limit=1)
        self.assertTrue(message, 'изменение поля создало сообщение')
        channel._streams_link_messages(message)
        self.assertIn(
            message.id, self._feed_ids(channel),
            'в личном канале Changes фильтры потоков не применяются')

    # ------------------------------------------------------------
    # ОТМЕТКА ПРОЧТЕНИЯ (решение Р4 фазы 8)
    # ------------------------------------------------------------

    def _member_of(self, channel, user):
        return self.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', user.partner_id.id),
        ], limit=1)

    def test_15_mark_read_returns_fresh_counter(self):
        partner, channel = self._start_discussion('Streams UI Mark Read')
        channel.sudo().add_members(partner_ids=self.internal_partner.ids)
        last = partner.message_post(
            body='unread for the reader', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        member = self._member_of(channel, self.internal_user)
        member.invalidate_recordset(['message_unread_counter'])
        self.assertTrue(
            member.message_unread_counter,
            'до отметки у читателя есть непрочитанное')

        result = channel.with_user(self.internal_user).streams_mark_read(
            last.id)
        self.assertEqual(
            result, {'unread': 0}, 'ответ несёт свежий счётчик')
        member.invalidate_recordset(['message_unread_counter'])
        self.assertEqual(member.message_unread_counter, 0)
        self.assertEqual(
            member.seen_message_id, last,
            'последнее прочитанное сообщение запомнено')

    def test_16_mark_read_covers_projections(self):
        """Отмечается прочитанным и сообщение-проекция записи (§5.7)."""
        partner, channel = self._start_discussion('Streams UI Mark Projection')
        channel.sudo().add_members(partner_ids=self.internal_partner.ids)
        projected = partner.message_post(
            body='projected comment', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.assertEqual(
            projected.model, 'res.partner',
            'сообщение живёт на записи, в канал приходит проекцией')

        channel.with_user(self.internal_user).streams_mark_read(projected.id)
        member = self._member_of(channel, self.internal_user)
        self.assertEqual(member.seen_message_id, projected)

    def test_17_mark_read_is_forgiving(self):
        partner, channel = self._start_discussion('Streams UI Mark Guard')
        last = partner.message_ids[:1]
        # не участник: канал могли покинуть в параллельной вкладке
        self.assertFalse(
            channel.with_user(self.internal_user).streams_mark_read(last.id),
            'не участнику возвращается False, а не исключение')
        channel.sudo().add_members(partner_ids=self.internal_partner.ids)
        self.assertFalse(
            channel.with_user(self.internal_user).streams_mark_read(0),
            'без id сообщения ничего не отмечается')
