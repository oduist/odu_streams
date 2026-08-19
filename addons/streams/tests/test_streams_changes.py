# -*- encoding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import common, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestStreamsChanges(common.TransactionCase):
    """Подписка на поля и личный канал Changes (§4.3, §8)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tag = cls.env['res.partner.category'].create({
            'name': 'Streams Changes Tag'})
        cls.country = cls.env.ref('base.pl')
        cls.group_user = cls.env.ref('base.group_user')
        # 19: groups_id переименовано в group_ids
        cls.watcher = cls.env['res.users'].create({
            'name': 'Streams Watcher',
            'login': 'streams.watcher@example.com',
            'group_ids': [(6, 0, [cls.group_user.id])],
        })
        cls.other_user = cls.env['res.users'].create({
            'name': 'Streams Other',
            'login': 'streams.other@example.com',
            'group_ids': [(6, 0, [cls.group_user.id])],
        })
        partner_fields = cls.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'),
            ('name', 'in', ['email', 'phone']),
        ])
        cls.field_email = partner_fields.filtered(
            lambda field: field.name == 'email')
        cls.field_phone = partner_fields.filtered(
            lambda field: field.name == 'phone')

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

    def _subscribe(self, record, user, fields_records):
        return record.with_user(user).streams_set_field_subscription(
            fields_records.ids)

    def _changes_channel(self, user, create=False):
        return self.env['discuss.channel']._streams_get_changes_channel(
            user, create=create)

    def _feed(self, user, **kwargs):
        channel = self._changes_channel(user)
        self.assertTrue(channel, 'у подписчика должен быть канал Changes')
        return channel.with_user(user).streams_changes_feed(**kwargs)

    def _member(self, user):
        """Участник личного канала Changes пользователя."""
        channel = self._changes_channel(user)
        return self.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', user.partner_id.id),
        ], limit=1)

    def _unread(self, user):
        # 19: счётчик непрочитанного живёт на участнике канала
        member = self._member(user).with_user(user).sudo()
        member.invalidate_recordset(['message_unread_counter'])
        return member.message_unread_counter

    def _record_channel(self, record):
        return self.env['discuss.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])

    # 1
    def test_01_subscription_upsert_uniqueness_and_rules(self):
        partner = self._make_partner('Changes Subscription')
        subscription_model = self.env['mail.field.subscription']

        self._subscribe(partner, self.watcher, self.field_email)
        subscription = subscription_model._streams_find(
            'res.partner', partner.id, user=self.watcher)
        self.assertEqual(subscription.field_ids, self.field_email)

        # повторная подписка обновляет ту же запись, а не создаёт вторую
        self._subscribe(partner, self.watcher, self.field_email | self.field_phone)
        again = subscription_model._streams_find(
            'res.partner', partner.id, user=self.watcher)
        self.assertEqual(again, subscription, 'подписка одна на запись')
        self.assertEqual(again.field_ids, self.field_email | self.field_phone)

        # чужие подписки не видны: ir.rule «только свои»
        self._subscribe(partner, self.other_user, self.field_phone)
        visible = subscription_model.with_user(self.watcher).search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)])
        self.assertEqual(
            visible.user_id, self.watcher,
            'пользователь видит только собственные подписки')

        # пустой список = отписка
        partner.with_user(self.watcher).streams_set_field_subscription([])
        self.assertFalse(
            subscription_model._streams_find(
                'res.partner', partner.id, user=self.watcher),
            'пустой выбор снимает подписку целиком')

    # 2
    def test_02_available_fields_prefill_and_access(self):
        partner = self._make_partner('Changes Available')
        state = partner.with_user(self.watcher).streams_get_field_subscription()
        self.assertFalse(state['subscribed'])
        self.assertTrue(state['available_fields'])

        prefilled = set(state['field_ids'])
        self.assertIn(
            self.field_email.id, prefilled,
            'при первом открытии предлагаются трекаемые поля')
        available_ids = {item['id'] for item in state['available_fields']}
        by_id = {item['id']: item for item in state['available_fields']}
        self.assertTrue(by_id[self.field_email.id]['tracking'])
        self.assertTrue(
            all(by_id[field_id]['tracking'] for field_id in prefilled),
            'предзаполнение — ровно трекаемые поля')

        # поле с groups=, к которому у обычного пользователя доступа нет,
        # в диалоге не показывается вовсе (§8.1)
        restricted = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'signup_type')], limit=1)
        self.assertTrue(
            restricted, 'ожидается поле signup_type с groups=base.group_erp_manager')
        self.assertTrue(self.env['res.partner']._fields['signup_type'].groups)
        self.assertFalse(
            self.watcher.has_group('base.group_erp_manager'),
            'подопытный пользователь не должен состоять в группе поля')
        self.assertNotIn(restricted.id, available_ids)

        # служебные поля чаттера тоже не предлагаем
        available_names = {item['name'] for item in state['available_fields']}
        self.assertFalse(
            {name for name in available_names
             if name.startswith(('message_', 'activity_', 'write_', 'create_'))},
            'служебные поля в диалоге не нужны')

        # выбор пользователя приоритетнее предзаполнения
        self._subscribe(partner, self.watcher, self.field_phone)
        state = partner.with_user(self.watcher).streams_get_field_subscription()
        self.assertTrue(state['subscribed'])
        self.assertEqual(state['field_ids'], self.field_phone.ids)

    # 3
    def test_03_change_lands_in_both_channels_filtered_by_subscription(self):
        partner = self._make_partner('Changes Both')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        record_channel = self._record_channel(partner)
        self.assertTrue(record_channel)
        self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()

        before = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id)])
        partner.write({
            'email': 'changes.both.updated@example.com',
            'phone': '+48 111 222 333'})
        self._flush_tracking()
        new_messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id)]) - before
        self.assertEqual(
            len(new_messages), 1,
            'изменения одного write остаются одним сообщением')

        changes_channel = self._changes_channel(self.watcher)
        self.assertTrue(changes_channel)
        self.assertEqual(
            new_messages.stream_channel_ids,
            record_channel | changes_channel,
            'одно сообщение подшито и к каналу записи, и к личному каналу')

        feed = self._feed(self.watcher)
        self.assertEqual(len(feed), 1)
        item = feed[0]
        self.assertEqual(item['res_model'], 'res.partner')
        self.assertEqual(item['res_id'], partner.id)
        self.assertEqual(item['record_name'], partner.display_name)
        self.assertEqual(len(item['changes']), 1)
        values = item['changes'][0]['values']
        self.assertEqual(
            [value['field_name'] for value in values], ['email'],
            'в личной ленте видно только подписанное поле')
        self.assertEqual(values[0]['new'], 'changes.both.updated@example.com')

    # 4
    def test_04_subscriber_outside_record_channel(self):
        partner = self._make_partner('Changes Outsider')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        record_channel = self._record_channel(partner)
        self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()

        self.assertNotIn(
            self.watcher.partner_id, record_channel.channel_partner_ids,
            'подписка на поля участником канала записи не делает')
        self.assertNotIn(
            self.watcher.partner_id, partner.message_partner_ids,
            'подписка на поля follower-ом не делает')

        partner.write({'email': 'changes.outsider.updated@example.com'})
        self._flush_tracking()
        feed = self._feed(self.watcher)
        self.assertEqual(
            len(feed), 1,
            'не-участник канала записи всё равно получает изменения')

    # 5
    def test_05_author_sees_own_change(self):
        partner = self._make_partner('Changes Author')
        # в этой базе право на правку контакта у group_user урезано
        self.watcher.write({
            'group_ids': [(4, self.env.ref('base.group_partner_manager').id)]})
        # правим телефон, а не email: запись email на res.partner в этой базе
        # каскадится в prt.phone, куда обычному пользователю писать нельзя
        self._subscribe(partner, self.watcher, self.field_phone)
        self._flush_tracking()

        partner.with_user(self.watcher).write({'phone': '+48 500 400 300'})
        self._flush_tracking()

        feed = self._feed(self.watcher)
        self.assertEqual(
            len(feed), 1, 'автор изменения уведомляется наравне со всеми')
        change = feed[0]['changes'][0]
        self.assertEqual(change['author_id'], self.watcher.partner_id.id)

    # 6
    def test_06_change_without_subscribers_stays_local(self):
        partner = self._make_partner('Changes Nobody')
        partner.message_post(
            body='Start', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        record_channel = self._record_channel(partner)
        self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()

        before = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id)])
        partner.write({'phone': '+48 999 888 777'})
        self._flush_tracking()
        message = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', partner.id)]) - before
        self.assertEqual(len(message), 1)
        self.assertEqual(
            message.stream_channel_ids, record_channel,
            'изменение неподписанного поля в личные каналы не идёт')
        self.assertFalse(
            self._feed(self.watcher),
            'в личной ленте показывать нечего')

    # 7
    def test_07_changes_channel_unread_counts_records(self):
        first = self._make_partner('Changes Unread One')
        second = self._make_partner('Changes Unread Two')
        for partner in (first, second):
            self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()

        for index, partner in enumerate((first, second)):
            for step in range(2):
                partner.write(
                    {'email': 'unread.%s.%s@example.com' % (index, step)})
                self._flush_tracking()

        self.assertEqual(
            self._unread(self.watcher), 2,
            'счётчик личного канала считает записи, а не изменения')

        channel = self._changes_channel(self.watcher)
        # 19: _channel_seen() удалён — прочтение это member._mark_as_read()
        last_message = self.env['mail.message'].sudo().search(
            channel._streams_message_domain(), order='id DESC', limit=1)
        self._member(self.watcher).with_user(
            self.watcher)._mark_as_read(last_message.id)
        self.assertEqual(
            self._unread(self.watcher), 0, 'просмотр обнуляет счётчик')

        feed = self._feed(self.watcher)
        self.assertEqual(
            [item['res_id'] for item in feed], [second.id, first.id],
            'свежая запись сверху')
        self.assertFalse(any(item['unread'] for item in feed))

        first.write({'email': 'unread.bump@example.com'})
        self._flush_tracking()
        feed = self._feed(self.watcher)
        self.assertEqual(
            [item['res_id'] for item in feed], [first.id, second.id],
            'новое изменение поднимает запись наверх ленты')
        self.assertTrue(feed[0]['unread'])
        self.assertEqual(self._unread(self.watcher), 1)

    # 8
    @mute_logger('odoo.models.unlink')
    def test_08_lost_access_hides_changes(self):
        partner = self._make_partner('Changes Lost Access')
        self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()
        partner.write({'email': 'changes.lost@example.com'})
        self._flush_tracking()

        self.assertEqual(len(self._feed(self.watcher)), 1)
        self.assertEqual(self._unread(self.watcher), 1)

        # глобальное правило: правила одной группы объединяются по ИЛИ, так
        # что сузить доступ можно только правилом без групп
        rule = self.env['ir.rule'].create({
            'name': 'Streams test: hide partner',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'domain_force': "[('id', '!=', %s)]" % partner.id,
            'groups': [(6, 0, [])],
        })
        self.env['res.partner'].invalidate_model()

        self.assertFalse(
            self._feed(self.watcher),
            'потеряв доступ к записи, пользователь не видит её изменений')
        self.assertEqual(
            self._unread(self.watcher), 0, 'счётчик пересчитывается')

        # сама привязка в БД сохраняется — доступ может вернуться
        channel = self._changes_channel(self.watcher)
        self.assertTrue(
            self.env['mail.message'].sudo().search_count(
                [('stream_channel_ids', 'in', channel.ids)]))

        rule.unlink()
        self.env['res.partner'].invalidate_model()
        self.assertEqual(len(self._feed(self.watcher)), 1)

    # 9
    def test_09_mass_write_routes_in_batch(self):
        partners = self.env['res.partner']
        for index in range(50):
            partners |= self._make_partner('Changes Mass %s' % index)
        for partner in partners:
            self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()

        before = self.env['mail.message'].sudo().search_count(
            [('model', '=', 'res.partner'), ('res_id', 'in', partners.ids)])
        partners.write({'email': 'changes.mass@example.com'})
        self._flush_tracking()
        after = self.env['mail.message'].sudo().search_count(
            [('model', '=', 'res.partner'), ('res_id', 'in', partners.ids)])
        self.assertEqual(
            after - before, 50, 'по одному сообщению на запись')

        channel = self._changes_channel(self.watcher)
        self.assertEqual(
            self.env['mail.message'].sudo().search_count([
                ('stream_channel_ids', 'in', channel.ids),
                ('res_id', 'in', partners.ids),
            ]), 50, 'все изменения подшиты к личному каналу')
        feed = self._feed(self.watcher, limit=60)
        self.assertEqual(len(feed), 50)

    # 10
    def test_10a_changes_feed_cursor(self):
        """Курсорная пагинация ленты (фаза 8, `with_cursor=True`).

        Отсев по подписке идёт ПОСЛЕ выборки страницы, поэтому страница
        может выйти пустой при непустом хвосте. Курсор — минимальный
        просмотренный `last_message_id` до отсева — обязан вести сквозь
        такие страницы, а `has_more` — не гаснуть на них.
        """
        subscribed = self._make_partner('Cursor Subscribed')
        skipped = self._make_partner('Cursor Skipped')
        self._subscribe(subscribed, self.watcher, self.field_email)
        self._subscribe(skipped, self.watcher, self.field_email)
        self._flush_tracking()
        # значения обязаны отличаться от выставленных в `_make_partner`,
        # иначе write не даст tracking-сообщения вовсе
        subscribed.write({'email': 'cursor.subscribed.v2@example.com'})
        self._flush_tracking()
        skipped.write({'email': 'cursor.skipped.v2@example.com'})
        self._flush_tracking()
        # снять подписку ПОСЛЕ маршрутизации: сообщение уже подшито к
        # каналу (цель в выборке останется), но лента такую запись целиком
        # отсеет — ровно случай «пустая страница при непустом хвосте»
        skipped.with_user(self.watcher).streams_set_field_subscription([])
        self._flush_tracking()

        # дефолтная форма — по-прежнему голый список (мобильный контракт)
        plain = self._feed(self.watcher)
        self.assertIsInstance(plain, list)

        # страница из одной цели: самая свежая (skipped) отсеется целиком,
        # но курсор и has_more обязаны позволить дойти до subscribed
        page = self._feed(self.watcher, limit=1, with_cursor=True)
        self.assertEqual(page['items'], [],
                         'цель без подписки на изменённое поле отсеяна')
        self.assertTrue(page['has_more'],
                        'сырая страница полна — хвост не просмотрен')
        self.assertTrue(page['cursor'])

        page = self._feed(self.watcher, limit=1, with_cursor=True,
                          before_id=page['cursor'])
        self.assertEqual(
            [item['res_id'] for item in page['items']], [subscribed.id],
            'курсор провёл через отсеянную страницу')

        # хвост кончился: курсор либо None, либо доводит до пустой
        # страницы без has_more
        if page['has_more']:
            page = self._feed(self.watcher, limit=30, with_cursor=True,
                              before_id=page['cursor'])
            self.assertFalse(page['has_more'])

    def test_10_changes_feed_is_private(self):
        partner = self._make_partner('Changes Private')
        self._subscribe(partner, self.watcher, self.field_email)
        self._flush_tracking()
        channel = self._changes_channel(self.watcher)
        self.assertEqual(channel.owner_user_id, self.watcher)
        self.assertEqual(
            channel.sudo().channel_partner_ids, self.watcher.partner_id,
            'личный канал состоит из одного участника — владельца')
        with self.assertRaises(AccessError):
            channel.with_user(self.other_user).streams_changes_feed()
