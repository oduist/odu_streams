# -*- encoding: utf-8 -*-
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestStreamsTours(HttpCase):
    """Tour-тесты веб-UI фазы 8 (`static/tests/tours/*.js`).

    Требуют Chrome/Chromium в окружении: без него `HttpCase.start_tour`
    поднимает `SkipTest`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # туры проходят от лица admin — фикстуры делаются его же правами,
        # иначе автор сообщения (а с ним и участник канала) будет OdooBot
        cls.admin = cls.env.ref('base.user_admin')

    def test_chatter_tour(self):
        """Кнопки чаттера и оба внутренних потока (§11.1)."""
        record = self.env['res.partner'].create({'name': 'Streams Chatter Tour'})
        self.start_tour(
            '/odoo/res.partner/%s' % record.id,
            'streams_chatter_tour',
            login='admin',
        )
        messages = record.message_ids.sorted('id')
        bodies = [message.body for message in messages]
        self.assertTrue(
            any('Internal comment from tour' in body for body in bodies),
            'комментарий из тура попал в чаттер записи')
        self.assertTrue(
            any('Internal note from tour' in body for body in bodies),
            'заметка из тура попала в чаттер записи')
        channel = self.env['discuss.channel'].sudo().search([
            ('channel_kind', '=', 'record'),
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', record.id),
        ])
        self.assertTrue(channel, 'первое сообщение завело канал записи')
        self.assertIn(
            channel, messages.sudo().stream_channel_ids,
            'сообщения чаттера спроецированы в канал записи')

    def test_channel_tour(self):
        """Канал записи в Discuss: сайдбар, композер, фильтры (§11.2)."""
        record = self.env['res.partner'].create({'name': 'Streams Tour Record'})
        # первый триггер §5.1: комментарий заводит канал и делает автора
        # его участником — иначе канала не будет в сайдбаре admin
        record.with_user(self.admin).message_post(
            body='Seed message', message_type='comment',
            subtype_xmlid='mail.mt_comment')
        channel = self.env['discuss.channel'].sudo().search([
            ('channel_kind', '=', 'record'),
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', record.id),
        ])
        self.assertTrue(channel, 'фикстура завела канал записи')
        self.assertIn(
            self.admin.partner_id, channel.channel_partner_ids,
            'автор комментария — участник канала (§5.3)')
        self.start_tour(
            '/odoo/action-mail.action_discuss',
            'streams_channel_tour',
            login='admin',
        )
        self.assertTrue(
            record.message_ids.filtered(
                lambda message: 'Comment from the record channel' in (
                    message.body or '')),
            'сообщение из канала записи спроецировано в чаттер записи')
        member = channel.channel_member_ids.filtered(
            lambda m: m.partner_id == self.admin.partner_id)
        self.assertEqual(
            member._streams_get_filters()['note'], True,
            'тумблер Notes вернулся во включённое состояние')

    def test_partner_scope_tour(self):
        """Переключатель охвата чаттера контакта (§18.2).

        Ветка реестра берётся установленная — `crm.lead.partner_id`
        (сид Р9): тур обязан проверять настоящую цепочку
        «реестр → SQL VIEW → `_message_fetch`», а не тестовую строку.
        Без crm пропускается: streams от него не зависит.
        """
        if 'crm.lead' not in self.env:
            self.skipTest('crm не установлен: ветка реестра недоступна')
        company = self.env['res.partner'].create({
            'name': 'Streams Scope Tour Company', 'is_company': True})
        contact = self.env['res.partner'].create({
            'name': 'Streams Scope Tour Contact', 'parent_id': company.id})
        lead = self.env['crm.lead'].create({
            'name': 'Streams Scope Tour Lead', 'partner_id': contact.id})
        contact.with_user(self.admin).message_post(
            body='Contact own message for the scope tour',
            message_type='comment', subtype_xmlid='mail.mt_comment')
        lead.with_user(self.admin).message_post(
            body='Lead message for the scope tour',
            message_type='comment', subtype_xmlid='mail.mt_comment')
        # старт с заведомого Related: настройка персистентная, и её
        # значение из чужого прогона сделало бы первый шаг случайным
        settings = self.env['res.users.settings']._find_or_create_for_user(
            self.admin)
        settings.streams_partner_scope = 'related'
        self.start_tour(
            '/odoo/res.partner/%s' % contact.id,
            'streams_partner_scope_tour',
            login='admin',
        )
        self.assertEqual(
            settings.streams_partner_scope, 'related',
            'тур вернул охват в Related')

    def test_notify_tour(self):
        """Композер приоритетного уведомления (§12.2).

        Попап у получателя туром не проверяется: он всплывает в сессии
        второго пользователя, которой у тура нет. Эта половина покрыта
        Hoot-тестом `notify_popup.test.js` и `tests/test_streams_notify.py`.
        """
        record = self.env['res.partner'].create({'name': 'Streams Notify Tour'})
        mate = self.env['res.users'].create({
            'name': 'Streams Tour Mate',
            'login': 'streams.tour.mate',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.start_tour(
            '/odoo/res.partner/%s' % record.id,
            'streams_notify_tour',
            login='admin',
        )
        notify = self.env['mail.notify'].sudo().search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', record.id),
        ])
        self.assertEqual(len(notify), 1, 'тур отправил ровно одно уведомление')
        self.assertEqual(
            notify.recipient_ids.user_id, mate,
            'получателем стал выбранный в поиске пользователь')
        self.assertIn('Please check this record', notify.body or '')
