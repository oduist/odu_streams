# -*- encoding: utf-8 -*-
"""Политика мобильных пушей по потокам (§4 design-phase6).

Точки входа: `mail.thread._streams_broadcast` (проекции записи) и
`mail.notify._streams_broadcast_new` (уведомления). Отправка идёт через
queue_job: в тестах `with_delay` создаёт записи `queue.job`, а не исполняет
их, поэтому переходы состояний проверяются прямым вызовом
`_streams_process()` / `_streams_cron_process()`. Ключей FCM в тестах нет —
обработанные пуши получают state='skipped' ('fcm not configured'); сама
запись `streams.mobile.push` с правильным device_id и есть проверяемый факт
доставки.
"""
import base64
import json

from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestMobilePush(common.TransactionCase):
    """Подопытная запись — res.partner (как в тестах streams)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        # 19: mail.message._check_access('create') требует write-доступ к
        # записи-источнику (или followers) — как в тестах streams
        group_partner = cls.env.ref('base.group_partner_manager')
        cls.author = cls.env['res.users'].create({
            'name': 'Streams Push Author',
            'login': 'streams.push.author@example.com',
            'group_ids': [(6, 0, [group_user.id, group_partner.id])],
        })
        cls.member = cls.env['res.users'].create({
            'name': 'Streams Push Member',
            'login': 'streams.push.member@example.com',
            'group_ids': [(6, 0, [group_user.id, group_partner.id])],
        })
        # третий внутренний: чтение записи у него отберёт ir.rule (тест 4)
        cls.outsider = cls.env['res.users'].create({
            'name': 'Streams Push Outsider',
            'login': 'streams.push.outsider@example.com',
            'group_ids': [(6, 0, [group_user.id, group_partner.id])],
        })
        device_model = cls.env['streams.mobile.device']
        cls.author_device, cls.author_token = device_model._streams_issue(
            cls.author, name='Author phone', platform='android')
        cls.member_device, cls.member_token = device_model._streams_issue(
            cls.member, name='Member phone', platform='ios')
        cls.outsider_device, cls.outsider_token = device_model._streams_issue(
            cls.outsider, name='Outsider phone', platform='android')
        # FCM-токены: без них обработка пропускала бы пуш с 'no push token'
        cls.author_device.write({'push_token': 'fcm-author'})
        cls.member_device.write({'push_token': 'fcm-member'})
        cls.outsider_device.write({'push_token': 'fcm-outsider'})

    # ------------------------------------------------------------
    # Хелперы
    # ------------------------------------------------------------

    def _flush_tracking(self):
        """Трекинг в 19 отложен до precommit — без него сообщения нет."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _make_record(self, name):
        record = self.env['res.partner'].create({
            'name': name,
            'email': '%s@example.com' % name.lower().replace(' ', '.'),
        })
        # 19: create ставит discard-маркер трекинга — сбрасываем, чтобы
        # последующие write в тестах давали change-сообщения честно
        self._flush_tracking()
        return record

    def _post(self, record, user, body, subtype='mail.mt_comment', **kwargs):
        return record.with_user(user).message_post(
            body=body, message_type='comment', subtype_xmlid=subtype,
            **kwargs)

    def _channel_of(self, record):
        return self.env['discuss.channel'].sudo().with_context(
            active_test=False).search([
                ('channel_kind', '=', 'record'),
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])

    def _pushes(self):
        return self.env['streams.mobile.push'].sudo().search([])

    def _start_discussion(self, name):
        """Запись + канал: первый комментарий автора (он же участник)."""
        record = self._make_record(name)
        self._post(record, self.author, 'Start')
        return record, self._channel_of(record)

    # 1
    def test_01_comment_pushes_members_except_author(self):
        record = self._make_record('Streams Push Comment')
        before = self._pushes()
        self._post(record, self.author, 'First comment')
        self.assertFalse(
            self._pushes() - before,
            'первый комментарий: в канале один автор — пушей нет')

        record.message_subscribe(partner_ids=self.member.partner_id.ids)
        channel = self._channel_of(record)
        self.assertIn(
            self.member.partner_id, channel.sudo().channel_partner_ids)

        before = self._pushes()
        message = self._post(record, self.author, 'Second comment')
        new = self._pushes() - before
        self.assertEqual(
            new.mapped('device_id'), self.member_device,
            'comment пушится участникам канала, кроме автора; '
            'без упоминаний — только участникам')
        self.assertEqual(
            new.state, 'queued', 'постановка синхронна, отправка — job')
        data = json.loads(new.data)
        self.assertEqual(data['kind'], 'comment')
        self.assertEqual(data['channel_id'], channel.id)
        self.assertEqual(data['message_id'], message.id)

        new._streams_process()
        self.assertEqual(
            new.state, 'skipped',
            'без ключей FCM транспорт-заглушка пропускает пуш')
        self.assertEqual(new.error, 'fcm not configured')

    # 2
    def test_02_note_pushes_only_mentioned(self):
        record, _channel = self._start_discussion('Streams Push Note')
        # участник канала без упоминания — пуша не получит
        record.message_subscribe(partner_ids=self.outsider.partner_id.ids)

        before = self._pushes()
        self._post(
            record, self.author, 'Private note', subtype='mail.mt_note',
            partner_ids=self.member.partner_id.ids)
        new = self._pushes() - before
        self.assertEqual(
            new.mapped('device_id'), self.member_device,
            'note пушится ТОЛЬКО явно упомянутым (partner_ids сообщения): '
            'ни автору, ни участникам без упоминания')

    # 3
    def test_03_change_and_activity_produce_no_push(self):
        record, _channel = self._start_discussion('Streams Push Change')
        record.message_subscribe(partner_ids=self.member.partner_id.ids)
        self._flush_tracking()

        before = self._pushes()
        record.write({'email': 'push.change@example.com'})
        self._flush_tracking()
        self.assertFalse(
            self._pushes() - before, 'change пушей не порождает никогда')

        self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get('res.partner').id,
            'res_id': record.id,
            'activity_type_id': self.env.ref(
                'mail.mail_activity_data_todo').id,
            'summary': 'Call the customer',
            'user_id': self.env.user.id,
        })
        self._flush_tracking()
        self.assertFalse(
            self._pushes() - before, 'activity пушей не порождает никогда')

    # 4
    def test_04_member_without_read_access_gets_no_push(self):
        record, channel = self._start_discussion('Streams Push Acl')
        record.message_subscribe(partner_ids=(
            self.member.partner_id | self.outsider.partner_id).ids)
        self.assertIn(
            self.outsider.partner_id, channel.sudo().channel_partner_ids,
            'до отбора прав outsider — обычный участник канала')

        # правило видит user из контекста оценки: запись закрыта только
        # для outsider, остальным — полный доступ (образец — test_09 UI)
        rule = self.env['ir.rule'].sudo().create({
            'name': 'streams_mobile: deny record for outsider',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'domain_force':
                "[('id', '!=', %d)] if user.id == %d else [(1, '=', 1)]"
                % (record.id, self.outsider.id),
            'groups': [(6, 0, [])],
            'perm_read': True,
            'perm_write': False,
            'perm_create': False,
            'perm_unlink': False,
        })
        try:
            before = self._pushes()
            self._post(record, self.author, 'Members only')
            new = self._pushes() - before
            self.assertEqual(
                new.mapped('device_id'), self.member_device,
                'участник без права чтения записи пуш не получает '
                '(ACL как у bus-рассылки)')
        finally:
            rule.unlink()

    # 5
    def test_05_notify_pushes_all_recipients(self):
        # мьют звука уведомлений не влияет на пуш (политика ТЗ: всегда всем)
        settings = self.env['res.users.settings']._find_or_create_for_user(
            self.member)
        settings.write({'is_streams_notify_sound_muted': True})

        before = self._pushes()
        result = self.env['mail.notify'].with_user(
            self.author).streams_notify_send({
                'body': 'Hello push',
                'user_ids': [self.member.id, self.outsider.id],
            })
        new = self._pushes() - before
        self.assertEqual(
            new.mapped('device_id'), self.member_device | self.outsider_device,
            'notify пушится всем получателям, включая замьюченных')
        self.assertNotIn(
            self.author_device, new.mapped('device_id'),
            'автор не получатель — пуша ему нет')
        for push in new:
            self.assertEqual(
                push.body, 'Hello push',
                'тело пуша — plaintext, без html-обёртки уведомления')
            self.assertEqual(json.loads(push.data)['type'], 'notify')
            self.assertEqual(json.loads(push.data)['notify_id'], result['id'])

        # голосовое без текста — 'Voice message'
        voice = self.env['ir.attachment'].with_user(self.author).create({
            'name': 'voice.webm',
            'datas': base64.b64encode(b'fake-audio-payload'),
            'mimetype': 'audio/webm',
            'res_model': 'mail.compose.message',
            'res_id': 0,
        })
        before = self._pushes()
        self.env['mail.notify'].with_user(self.author).streams_notify_send({
            'body': '',
            'user_ids': [self.member.id],
            'voice_attachment_id': voice.id,
            'voice_duration': 5,
        })
        new = self._pushes() - before
        self.assertEqual(new.mapped('device_id'), self.member_device)
        self.assertEqual(
            new.body, 'Voice message',
            'голосовое уведомление без текста подписывается Voice message')

    # 6
    def test_06_device_states(self):
        partner = self.member.partner_id
        push_model = self.env['streams.mobile.push']

        # push_enabled=False — запись пуша не создаётся вовсе
        self.member_device.write({'push_enabled': False})
        self.assertFalse(
            push_model._streams_enqueue(partner, 'Title', 'Body'),
            'выключенные пуши устройства — пуш не ставится')
        self.assertFalse(push_model.sudo().search([
            ('device_id', '=', self.member_device.id)]))

        # устройство без push_token — пуш ставится, но пропускается
        self.member_device.write({'push_enabled': True, 'push_token': False})
        pushes = push_model._streams_enqueue(partner, 'Title', 'Body')
        self.assertEqual(pushes.mapped('device_id'), self.member_device)
        pushes._streams_process()
        self.assertEqual(pushes.state, 'skipped')
        self.assertEqual(pushes.error, 'no push token')

        # отозванное устройство пушей не получает
        self.member_device.write({'push_token': 'fcm-member-again'})
        self.member_device.action_revoke()
        self.assertFalse(
            push_model._streams_enqueue(partner, 'Title', 'Body'),
            'отозванное (архивированное) устройство из выборки исключено')

    # 7
    def test_07_enqueue_empty_and_cron_process(self):
        push_model = self.env['streams.mobile.push']
        self.assertFalse(
            push_model._streams_enqueue(
                self.env['res.partner'], 'Title', 'Body'),
            'пустые partners — пусто, без падений')

        job_domain = [
            ('model_name', '=', 'streams.mobile.push'),
            ('method_name', '=', '_streams_process'),
        ]
        jobs_before = self.env['queue.job'].sudo().search_count(job_domain)
        pushes = push_model._streams_enqueue(
            self.member.partner_id, 'Title', 'Body', data={'k': 'v'})
        self.assertEqual(pushes.mapped('device_id'), self.member_device)
        self.assertEqual(pushes.state, 'queued')
        self.assertGreater(
            self.env['queue.job'].sudo().search_count(job_domain),
            jobs_before,
            'доставка поставлена job-ом queue_job (в тестах не исполняется)')

        # cron-страховка доотправляет queued; без ключей FCM — skipped
        push_model._streams_cron_process()
        self.assertEqual(pushes.state, 'skipped')
        self.assertEqual(pushes.error, 'fcm not configured')
