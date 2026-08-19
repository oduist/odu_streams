# -*- encoding: utf-8 -*-
"""Виртуальный чаттер контакта (§18, фаза 9).

Лента карточки контакта — агрегатор: показывает сообщения связанных
записей, не перенося их. Проверяется реестр источников, живучесть SQL
VIEW, три уровня охвата, права (ничего чужого — ни телом, ни фактом),
добор страницы после ACL и оба инварианта §18.5–18.6: канал контакта и
счётчики непрочитанного не меняются, needaction чужих записей не гасится.
"""
from odoo.exceptions import ValidationError
from odoo.tests import common, tagged
from odoo.tools import mute_logger

from odoo.addons.streams.models.streams_partner_source import (
    STREAMS_PARTNER_VIEW)


class StreamsPartnerFeedCommon(common.TransactionCase):
    """Фикстуры ленты: организация, два контакта и запись-источник.

    Сторонней моделью с m2o на контрагента в этой среде является только
    `crm.lead` (см. отчёт core §7.1), а модуль от crm не зависит и
    зависеть не должен. Поэтому базовая ветка агрегации в тестах —
    строка реестра `res.partner.parent_id`: она даёт ровно ту же
    механику (чужая запись со ссылкой на контрагента), но не требует ни
    одного стороннего модуля. Ветка crm проверяется отдельно.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_partner_manager = cls.env.ref('base.group_partner_manager')
        cls.source_model = cls.env['streams.partner.source']
        cls.user = cls.env['res.users'].create({
            'name': 'Streams Feed User',
            'login': 'streams.feed.user@example.com',
            'group_ids': [(6, 0, [
                cls.group_user.id, cls.group_partner_manager.id])],
        })
        cls.company = cls.env['res.partner'].create({
            'name': 'Streams Feed Company', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Streams Feed Contact', 'parent_id': cls.company.id})
        cls.other_contact = cls.env['res.partner'].create({
            'name': 'Streams Feed Other', 'parent_id': cls.company.id})
        cls.outsider = cls.env['res.partner'].create({
            'name': 'Streams Feed Outsider'})

    # ------------------------------------------------------------
    # ХЕЛПЕРЫ
    # ------------------------------------------------------------

    @classmethod
    def _register_source(cls, model_name, field_name):
        """Добавить строку реестра (и пересобрать вьюху)."""
        return cls.source_model.create({
            'model_id': cls.env['ir.model']._get(model_name).id,
            'field_id': cls.env['ir.model.fields']._get(
                model_name, field_name).id,
        })

    def _flush_tracking(self):
        """Трекинг в Odoo 19 отложен до precommit — без него сообщения нет."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _post(self, record, body, subtype='mail.mt_comment', **kwargs):
        message = record.message_post(
            body=body, message_type='comment', subtype_xmlid=subtype,
            **kwargs)
        self._flush_tracking()
        return message

    def _scope(self, scope, user=None):
        user = user or self.user
        settings = self.env['res.users.settings'].sudo(
        )._find_or_create_for_user(user)
        settings.write({'streams_partner_scope': scope})
        return settings

    def _feed(self, partner, scope=None, user=None, context=None, **kwargs):
        """Лента чаттера контакта глазами пользователя."""
        user = user or self.user
        if scope:
            self._scope(scope, user=user)
        message_model = self.env['mail.message'].with_user(user)
        if context:
            message_model = message_model.with_context(**context)
        kwargs.setdefault('limit', 30)
        result = message_model._message_fetch(
            None, thread=partner.with_user(user), **kwargs)
        return result['messages']

    def _bodies(self, messages):
        return {(message.body or '').strip() for message in messages}


@tagged('post_install', '-at_install')
class TestStreamsPartnerSource(StreamsPartnerFeedCommon):
    """Реестр источников и жизненный цикл вьюхи (§18.3, Р1, Р10)."""

    def _view_definition(self):
        self.env.cr.execute(
            "SELECT pg_get_viewdef(%s::regclass, true)", (STREAMS_PARTNER_VIEW,))
        return self.env.cr.fetchone()[0]

    def test_view_exists_with_partner_branch(self):
        """Вьюха есть всегда и всегда содержит ветку самого контакта."""
        self.assertTrue(self.source_model._streams_view_available())
        self.assertIn('res_partner', self._view_definition())

    def test_view_follows_registry(self):
        """CRUD реестра пересобирает вьюху."""
        source = self._register_source('res.partner', 'parent_id')
        self.assertIn('parent_id', self._view_definition())
        source.write({'active': False})
        self.assertNotIn('parent_id', self._view_definition())
        source.write({'active': True})
        self.assertIn('parent_id', self._view_definition())
        source.unlink()
        self.assertNotIn('parent_id', self._view_definition())

    def test_view_recreated_after_drop(self):
        """Каскадный снос вьюхи лечится сверкой сигнатуры (Р10)."""
        self.env.cr.execute('DROP VIEW IF EXISTS %s' % STREAMS_PARTNER_VIEW)
        self.assertFalse(self.source_model._streams_view_available())
        self.assertTrue(self.source_model._streams_ensure_view())
        self.assertTrue(self.source_model._streams_view_available())
        # определение не менялось — второй раз пересобирать нечего
        self.assertFalse(self.source_model._streams_ensure_view())

    def test_validation_rejects_non_partner_field(self):
        """Поле обязано быть хранимым m2o на res.partner."""
        with self.assertRaises(ValidationError):
            self._register_source('res.partner', 'name')

    def test_validation_rejects_foreign_field(self):
        """Поле должно принадлежать той же модели."""
        with self.assertRaises(ValidationError):
            self.source_model.create({
                'model_id': self.env['ir.model']._get('res.partner').id,
                'field_id': self.env['ir.model.fields']._get(
                    'res.users', 'partner_id').id,
            })

    def test_validation_rejects_model_without_chatter(self):
        """Модель без mail.thread сообщений не носит."""
        with self.assertRaises(ValidationError):
            self._register_source('res.users', 'partner_id')

    def test_registry_pair_is_unique(self):
        """Пара модель/поле регистрируется один раз."""
        self._register_source('res.partner', 'parent_id')
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self._register_source('res.partner', 'parent_id')

    def test_preview_counts_messages(self):
        """Предпросмотр отдаёт число сообщений ветки, а не сами сообщения."""
        source = self._register_source('res.partner', 'parent_id')
        self._post(self.contact, 'preview-body')
        action = source.action_preview()
        self.assertEqual(action['tag'], 'display_notification')
        expected = self.env['mail.message'].sudo().search_count(
            source._streams_branch_domain())
        self.assertTrue(expected)
        self.assertIn(str(expected), action['params']['message'])

    def test_seed_is_idempotent(self):
        """Повторный сид ничего не создаёт."""
        self.assertFalse(self.source_model._streams_seed_defaults())


@tagged('post_install', '-at_install')
class TestStreamsPartnerFeed(StreamsPartnerFeedCommon):
    """Три уровня охвата и правила видимости (§18.2, §18.4)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls._register_source('res.partner', 'parent_id')

    def test_direct_scope_is_untouched(self):
        """Direct — лента самой карточки, как до фазы 9."""
        self._post(self.company, 'company-body')
        self._post(self.contact, 'contact-body')
        messages = self._feed(self.company, 'direct')
        self.assertIn('<p>company-body</p>', self._bodies(messages))
        self.assertNotIn('<p>contact-body</p>', self._bodies(messages))
        self.assertTrue(all(
            message.model == 'res.partner'
            and message.res_id == self.company.id for message in messages))

    def test_related_scope_aggregates_linked_records(self):
        """Related — своё плюс записи, где контакт указан контрагентом."""
        self._post(self.company, 'company-body')
        self._post(self.contact, 'contact-body')
        self._post(self.other_contact, 'other-body')
        self._post(self.outsider, 'outsider-body')
        bodies = self._bodies(self._feed(self.company, 'related'))
        self.assertIn('<p>company-body</p>', bodies)
        self.assertIn('<p>contact-body</p>', bodies)
        self.assertIn('<p>other-body</p>', bodies)
        self.assertNotIn('<p>outsider-body</p>', bodies)

    def test_related_scope_of_contact_has_no_siblings(self):
        """Related контакта — только его собственные связанные записи."""
        self._post(self.contact, 'contact-body')
        self._post(self.other_contact, 'other-body')
        bodies = self._bodies(self._feed(self.contact, 'related'))
        self.assertIn('<p>contact-body</p>', bodies)
        self.assertNotIn('<p>other-body</p>', bodies)

    def test_company_scope_covers_all_contacts(self):
        """Company — связанный уровень всей организации."""
        self._post(self.company, 'company-body')
        self._post(self.contact, 'contact-body')
        self._post(self.other_contact, 'other-body')
        self._post(self.outsider, 'outsider-body')
        bodies = self._bodies(self._feed(self.contact, 'company'))
        self.assertIn('<p>company-body</p>', bodies)
        self.assertIn('<p>contact-body</p>', bodies)
        self.assertIn('<p>other-body</p>', bodies)
        self.assertNotIn('<p>outsider-body</p>', bodies)

    def test_virtual_change_and_service_messages_are_excluded(self):
        """Виртуальные change и «прочее» в агрегат не идут (§18.4)."""
        # трекинг создания фикстур должен уйти в лог до нашей правки,
        # иначе изменение сольётся с сообщением о создании записи
        self._flush_tracking()
        self.contact.sudo().write({'email': 'virtual.change@example.com'})
        self._flush_tracking()
        virtual_change = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', self.contact.id),
            ('tracking_value_ids', '!=', False)])
        self.assertTrue(virtual_change, 'изменение контакта должно записаться')
        service = self.env['mail.message'].sudo().create({
            'model': 'res.partner', 'res_id': self.contact.id,
            'body': '<p>service-body</p>', 'message_type': 'notification'})
        feed_ids = self._feed(self.company, 'related').ids
        self.assertNotIn(virtual_change.id, feed_ids)
        self.assertNotIn(service.id, feed_ids)

    def test_own_change_stays_visible(self):
        """Изменения самого контакта видны как раньше (§18.4)."""
        self._flush_tracking()
        self.company.sudo().write({'email': 'own.change@example.com'})
        self._flush_tracking()
        own_change = self.env['mail.message'].sudo().search([
            ('model', '=', 'res.partner'), ('res_id', '=', self.company.id),
            ('tracking_value_ids', '!=', False)])
        self.assertTrue(own_change)
        self.assertIn(own_change.id, self._feed(self.company, 'related').ids)

    def test_user_notification_never_shows_up(self):
        """Адресное служебное уведомление к ленте записи не относится."""
        notification = self.env['mail.message'].sudo().create({
            'model': 'res.partner', 'res_id': self.company.id,
            'body': '<p>user-notification</p>',
            'message_type': 'user_notification'})
        self.assertNotIn(
            notification.id, self._feed(self.company, 'related').ids)

    def test_direct_context_forces_direct_scope(self):
        """Контекст `streams_partner_direct` форсирует Direct (Р12)."""
        self._post(self.company, 'company-body')
        self._post(self.contact, 'contact-body')
        bodies = self._bodies(self._feed(
            self.company, 'company',
            context={'streams_partner_direct': True}))
        self.assertIn('<p>company-body</p>', bodies)
        self.assertNotIn('<p>contact-body</p>', bodies)

    def test_missing_view_degrades_to_direct(self):
        """Пропавшая вьюха гасит агрегат, а не чаттер (Р10)."""
        self._post(self.company, 'company-body')
        self._post(self.contact, 'contact-body')
        self.env.cr.execute('DROP VIEW IF EXISTS %s' % STREAMS_PARTNER_VIEW)
        with mute_logger('odoo.addons.streams.models.mail_message'):
            bodies = self._bodies(self._feed(self.company, 'related'))
        self.assertIn('<p>company-body</p>', bodies)
        self.assertNotIn('<p>contact-body</p>', bodies)
        self.source_model._streams_rebuild_view()
        self.assertIn(
            '<p>contact-body</p>',
            self._bodies(self._feed(self.company, 'related')))

    def test_pagination_before_and_around(self):
        """Пагинация ленты остаётся ядровой."""
        posted = [
            self._post(self.contact, 'page-%s' % index) for index in range(6)]
        page = self._feed(self.company, 'related', limit=3)
        self.assertEqual(len(page), 3)
        older = self._feed(self.company, 'related', limit=3, before=page[-1].id)
        self.assertFalse(set(page.ids) & set(older.ids))
        self.assertTrue(all(
            message_id < page[-1].id for message_id in older.ids))
        around = self._feed(
            self.company, 'related', limit=4, around=posted[2].id)
        self.assertIn(posted[2].id, around.ids)

    def test_scope_helper_defaults_to_related(self):
        """Без записи настроек охват — Related."""
        settings = self.env['res.users.settings'].sudo().search(
            [('user_id', '=', self.user.id)])
        settings.unlink()
        self.assertEqual(self.user._streams_partner_scope(), 'related')

    def test_company_scope_availability_key(self):
        """Ключ треда `streams_company_scope_available` (Р11)."""
        self.assertTrue(self.company._streams_company_scope_available())
        self.assertTrue(self.contact._streams_company_scope_available())
        lonely = self.env['res.partner'].create({'name': 'Streams Lonely'})
        self.assertFalse(lonely._streams_company_scope_available())


@tagged('post_install', '-at_install')
class TestStreamsPartnerFeedAccess(StreamsPartnerFeedCommon):
    """Права и добор страницы после ACL (§18.4, Р4)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls._register_source('res.partner', 'parent_id')
        cls.visible = cls.env['res.partner'].create({
            'name': 'Streams Feed Visible', 'parent_id': cls.company.id})
        cls.hidden = cls.env['res.partner'].create({
            'name': 'Streams Feed Hidden', 'parent_id': cls.company.id,
            'ref': 'streams-hidden'})
        # правило видимости ставится последним: фикстуры создаёт админ,
        # который тоже состоит в base.group_user
        cls.env['ir.rule'].create({
            'name': 'Streams feed hidden partners',
            'model_id': cls.env['ir.model']._get('res.partner').id,
            'domain_force': "[('ref', '!=', 'streams-hidden')]",
            'groups': [(6, 0, [cls.group_user.id])],
            'perm_read': True, 'perm_write': True,
            'perm_create': True, 'perm_unlink': True,
        })

    def test_hidden_record_messages_are_invisible(self):
        """Сообщения недоступной записи не видны ни телом, ни фактом."""
        self._post(self.visible, 'visible-body')
        hidden_message = self._post(self.hidden, 'hidden-body')
        messages = self._feed(self.company, 'related')
        self.assertIn('<p>visible-body</p>', self._bodies(messages))
        self.assertNotIn('<p>hidden-body</p>', self._bodies(messages))
        self.assertNotIn(hidden_message.id, messages.ids)

    def test_overfetch_fills_page_cut_by_acl(self):
        """Добор страницы: лимит применяется до ACL (Р4)."""
        visible_ids = [
            self._post(self.visible, 'visible-%s' % index).id
            for index in range(3)]
        for index in range(35):
            self._post(self.hidden, 'hidden-%s' % index)
        messages = self._feed(self.company, 'related', limit=30)
        self.assertTrue(
            set(visible_ids) <= set(messages.ids),
            'добор обязан вернуть доступные сообщения, срезанные лимитом')
        self.assertFalse(
            messages.filtered(lambda message: message.res_id == self.hidden.id),
            'сообщения недоступной записи в ленту попадать не должны')
        # без добора ядро отдало бы пустую страницу: 30 новейших до ACL —
        # сообщения недоступной записи
        domain = self.env['mail.message'].with_user(
            self.user)._streams_partner_domain(self.company.with_user(
                self.user))
        raw = self.env['mail.message'].with_user(self.user).search(
            domain, limit=30, order='id DESC')
        self.assertFalse(raw)


@tagged('post_install', '-at_install')
class TestStreamsPartnerChannelInvariants(StreamsPartnerFeedCommon):
    """Канал контакта и счётчики агрегация не трогает (§18.5, §18.6)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls._register_source('res.partner', 'parent_id')

    def _channel(self, record):
        return self.env['discuss.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])

    def test_linked_message_stays_out_of_partner_channel(self):
        """Сообщение связанной записи не подшивается к каналу контакта."""
        self._post(self.company, 'company-body')
        linked = self._post(self.contact, 'contact-body')
        company_channel = self._channel(self.company)
        self.assertTrue(company_channel)
        self.assertNotIn(company_channel.id, linked.sudo().stream_channel_ids.ids)
        channel_messages = self.env['mail.message'].sudo().search(
            company_channel._streams_message_domain())
        self.assertNotIn(linked.id, channel_messages.ids)
        # но в агрегированной ленте оно есть
        self.assertIn(linked.id, self._feed(self.company, 'related').ids)

    def test_feed_does_not_change_unread_counters(self):
        """Чтение агрегата счётчики непрочитанного не двигает."""
        self._post(self.company, 'company-body')
        channel = self._channel(self.company)
        member = self.env['discuss.channel.member'].sudo().create({
            'channel_id': channel.id,
            'partner_id': self.user.partner_id.id,
        })
        self._post(self.company, 'company-second')
        self._post(self.contact, 'contact-body')
        member.invalidate_recordset(['message_unread_counter'])
        before = member.message_unread_counter
        self._feed(self.company, 'company')
        member.invalidate_recordset(['message_unread_counter'])
        self.assertEqual(member.message_unread_counter, before)
        self.assertTrue(before, 'непрочитанное канала должно считаться')


@tagged('post_install', '-at_install')
class TestStreamsPartnerFeedCrm(StreamsPartnerFeedCommon):
    """Сторонняя модель реестра — та, что реально стоит в среде.

    Ветка crm проверяется отдельно и пропускается, если модуль не
    установлен: streams от crm не зависит и зависеть не должен (Р9).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'crm.lead' not in cls.env:
            return
        cls.user.write({'group_ids': [
            (4, cls.env.ref('sales_team.group_sale_salesman_all_leads').id)]})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Streams Feed Lead', 'partner_id': cls.contact.id})

    def test_seeded_crm_branch_feeds_partner(self):
        """Сообщение лида видно в Related контакта и в Company организации."""
        if 'crm.lead' not in self.env:
            self.skipTest('crm не установлен')
        self.assertTrue(self.source_model.search([
            ('model_id.model', '=', 'crm.lead'),
            ('field_id.name', '=', 'partner_id'),
        ]), 'сид должен зарегистрировать crm.lead.partner_id')
        message = self._post(self.lead, 'lead-body')
        self.lead.write({'name': 'Streams Feed Lead 2'})
        self._flush_tracking()
        change = self.env['mail.message'].sudo().search([
            ('model', '=', 'crm.lead'), ('res_id', '=', self.lead.id),
            ('tracking_value_ids', '!=', False)])
        related = self._feed(self.contact, 'related')
        self.assertIn(message.id, related.ids)
        self.assertNotIn(change.id, related.ids)
        self.assertIn(message.id, self._feed(self.company, 'company').ids)
        self.assertNotIn(message.id, self._feed(self.contact, 'direct').ids)


@tagged('post_install', '-at_install')
class TestStreamsPartnerFeedRoute(common.HttpCase):
    """Роут ленты: needaction чужих записей не гасится (Р8, §18.6)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].create({
            'name': 'Streams Feed Route User',
            'login': 'streams.feed.route',
            'password': 'streams.feed.route',
            'group_ids': [(6, 0, [
                group_user.id,
                cls.env.ref('base.group_partner_manager').id])],
        })
        cls.company = cls.env['res.partner'].create({
            'name': 'Streams Route Company', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Streams Route Contact', 'parent_id': cls.company.id})
        cls.env['streams.partner.source'].create({
            'model_id': cls.env['ir.model']._get('res.partner').id,
            'field_id': cls.env['ir.model.fields']._get(
                'res.partner', 'parent_id').id,
        })
        cls.env['res.users.settings'].sudo()._find_or_create_for_user(
            cls.user).write({'streams_partner_scope': 'related'})

    def _notification(self, message):
        return self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', message.id),
            ('res_partner_id', '=', self.user.partner_id.id),
        ], limit=1)

    def test_partner_chatter_keeps_foreign_needaction(self):
        """Просмотр чаттера контакта гасит только его собственные сообщения."""
        own = self.company.message_post(
            body='<p>own-body</p>', message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=[self.user.partner_id.id])
        foreign = self.contact.message_post(
            body='<p>foreign-body</p>', message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=[self.user.partner_id.id])
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.assertFalse(self._notification(own).is_read)
        self.assertFalse(self._notification(foreign).is_read)
        self.authenticate('streams.feed.route', 'streams.feed.route')
        result = self.make_jsonrpc_request('/mail/thread/messages', {
            'thread_model': 'res.partner',
            'thread_id': self.company.id,
            'fetch_params': {'limit': 30},
        })
        self.assertIn(own.id, result['messages'])
        self.assertIn(foreign.id, result['messages'])
        self.assertTrue(self._notification(own).is_read)
        self.assertFalse(
            self._notification(foreign).is_read,
            'needaction чужой записи гасить нельзя (§18.6)')
