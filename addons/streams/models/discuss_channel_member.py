# -*- encoding: utf-8 -*-
import json
import logging

from odoo import models, fields, api
from odoo.fields import Domain

from .mail_message import (
    STREAMS_FILTER_DEFAULTS, STREAM_ACTIVITY, STREAM_CHANGE,
    STREAM_REL_TABLE)

_logger = logging.getLogger(__name__)


class DiscussChannelMember(models.Model):
    """Зеркало «участник канала → follower записи» (§5.3).

    Обратное направление (follower → участник) живёт в
    `mail.thread.message_subscribe`. От рекурсии обе стороны защищены
    контекстом `streams_sync`.
    """
    _inherit = 'discuss.channel.member'

    streams_filters = fields.Char(
        string='Stream Filters',
        help="Per-user display filters of the record channel, stored as JSON.")

    def _streams_get_filters(self):
        """Фильтры участника поверх дефолтов (§6).

        Хранится JSON, а не набор булевых полей: список потоков ещё будет
        расти, а миграция схемы ради флажка отображения не нужна.
        """
        self.ensure_one()
        filters = dict(STREAMS_FILTER_DEFAULTS)
        if not self.streams_filters:
            return filters
        try:
            stored = json.loads(self.streams_filters)
        except (TypeError, ValueError):
            _logger.warning(
                'streams: битые фильтры участника %s: %r',
                self.id, self.streams_filters)
            return filters
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in filters:
                    filters[key] = bool(value)
        return filters

    def _streams_set_filters(self, filters):
        """Дописать переданные потоки в фильтры участника."""
        self.ensure_one()
        current = self._streams_get_filters()
        for key, value in (filters or {}).items():
            if key in STREAMS_FILTER_DEFAULTS:
                current[key] = bool(value)
        self.sudo().write({'streams_filters': json.dumps(current)})
        return current

    # ------------------------------------------------------------
    # ЗЕРКАЛО FOLLOWERS (§5.3)
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        members = super().create(vals_list)
        members._streams_mirror_followers(subscribe=True)
        return members

    def unlink(self):
        self._streams_mirror_followers(subscribe=False)
        return super().unlink()

    def _streams_mirror_followers(self, subscribe=True):
        if self.env.context.get('streams_sync'):
            return
        partners_by_record = {}
        for member in self.sudo():
            channel = member.channel_id
            if channel.channel_kind != 'record':
                continue
            if not channel.res_model or not channel.res_id:
                continue
            if not member.partner_id:
                continue
            partners_by_record.setdefault(
                (channel.res_model, channel.res_id), set()).add(
                    member.partner_id.id)
        for (res_model, res_id), partner_ids in partners_by_record.items():
            if res_model not in self.env:
                continue
            record = self.env[res_model].sudo().with_context(
                active_test=False).browse(res_id).exists()
            if not record:
                continue
            record = record.with_context(streams_sync=True)
            if subscribe:
                record.message_subscribe(partner_ids=list(partner_ids))
            else:
                record.message_unsubscribe(partner_ids=list(partner_ids))

    # ------------------------------------------------------------
    # НЕПРОЧИТАННОЕ (§5.7, §8.3, §12.5)
    # ------------------------------------------------------------

    def _compute_message_unread(self):
        """Счётчик непрочитанного; правила зависят от вида канала.

        В канале ЗАПИСИ изменения полей на счётчик не влияют (§5.7), в
        личном канале Changes они наоборот единственный его источник, а
        считаются там записи, а не сообщения (§8.3). В канале Notifications
        сообщений не бывает вовсе — счётчик берётся из уведомлений (§12.5).
        Ядровый SQL проекций не видит, поэтому наши виды каналов считаются
        своим запросом.
        """
        changes_members = self.filtered(
            lambda member: member.channel_id.channel_kind == 'changes')
        notify_members = self.filtered(
            lambda member: member.channel_id.channel_kind == 'notifications')
        record_members = self.filtered(
            lambda member: member.channel_id.channel_kind == 'record')
        core_members = self - changes_members - notify_members - record_members
        if core_members:
            super(DiscussChannelMember, core_members)._compute_message_unread()
        if changes_members:
            changes_members._streams_compute_changes_unread()
        if notify_members:
            notify_members._streams_compute_notify_unread()
        if record_members:
            record_members._streams_compute_record_unread()

    def _streams_compute_notify_unread(self):
        """Непрочитанное канала Notifications = непрочитанные уведомления."""
        counter = self.env['mail.notify']._streams_notify_counter()
        current_partner = self.env.user.partner_id
        for member in self:
            own = member.partner_id == current_partner \
                and member.channel_id.sudo().owner_user_id == self.env.user
            member.message_unread_counter = counter if own else 0

    def _streams_compute_changes_unread(self):
        """Непрочитанное личного канала Changes: число записей (§8.3).

        Права проверяются здесь же: запись, доступ к которой потерян,
        исчезает и из ленты, и из счётчика (§8.4). SQL этого не умеет,
        поэтому пары «модель+запись» отбираются запросом, а фильтрация
        по `ir.rule` идёт по одному `search` на модель. Счётчик имеет
        смысл только для владельца канала — им и ограничиваемся.
        """
        current_partner = self.env.user.partner_id
        channel_model = self.env['discuss.channel']
        for member in self:
            counter = 0
            if member.partner_id == current_partner \
                    and member.channel_id.sudo().owner_user_id == self.env.user:
                targets = member._streams_unread_change_targets()
                if targets:
                    counter = len(
                        channel_model._streams_readable_targets(targets))
            member.message_unread_counter = counter

    def _streams_unread_change_targets(self):
        """Записи с непрочитанными изменениями: [(model, res_id), ...]."""
        self.ensure_one()
        self.flush_recordset(['channel_id', 'seen_message_id'])
        self.env['mail.message'].flush_model()
        self.env.cr.execute(
            """
            SELECT DISTINCT msg.model AS model, msg.res_id AS res_id
              FROM discuss_channel_member m
              JOIN %s rel ON rel.channel_id = m.channel_id
              JOIN mail_message msg ON msg.id = rel.message_id
             WHERE m.id = %%s
               AND (m.seen_message_id IS NULL OR m.seen_message_id < msg.id)
               AND msg.model IS NOT NULL
               AND msg.model != 'discuss.channel'
               AND msg.res_id IS NOT NULL
            """ % STREAM_REL_TABLE,
            (self.id,))
        return [
            (row['model'], row['res_id'])
            for row in self.env.cr.dictfetchall()
        ]

    def _streams_compute_record_unread(self):
        """Счётчик по сообщениям канала и проекциям, без изменений полей.

        Форк ядрового `_compute_message_unread`: ядровый SQL знает только
        про `model='discuss.channel'` и проекции не видит, а изменения
        (`change`) по §5.7 не должны влиять на счётчик. Собственные
        сообщения участника не считаются (как в 15).

        `change` отсекается двумя условиями сразу: подтипом
        `streams.mt_change` (изменение поля) и типом `notification`
        (системный автолог, с 2026-08-20 тоже `change`); из notification
        считается только активность.
        """
        subtypes = self.env['mail.message']._streams_subtype_ids()
        change_subtype_id = subtypes.get(STREAM_CHANGE) or 0
        activity_subtype_id = subtypes.get(STREAM_ACTIVITY) or 0
        res = dict.fromkeys(self.ids, 0)
        if self.ids:
            self.flush_recordset(
                ['channel_id', 'partner_id', 'seen_message_id'])
            self.env['mail.message'].flush_model()
            self.env.cr.execute(
                """
                SELECT member_id, count(*)
                  FROM (
                        SELECT m.id AS member_id, msg.id AS message_id
                          FROM discuss_channel_member m
                          JOIN mail_message msg
                            ON msg.model = 'discuss.channel'
                           AND msg.res_id = m.channel_id
                         WHERE m.id = ANY(%%s)
                           AND (m.seen_message_id IS NULL
                                OR m.seen_message_id < msg.id)
                           AND msg.message_type NOT IN
                               ('notification', 'user_notification')
                           AND (msg.author_id IS NULL
                                OR m.partner_id IS NULL
                                OR msg.author_id != m.partner_id)
                           AND (msg.subtype_id IS NULL
                                OR msg.subtype_id != %%s)
                         UNION
                        SELECT m.id AS member_id, msg.id AS message_id
                          FROM discuss_channel_member m
                          JOIN %s rel ON rel.channel_id = m.channel_id
                          JOIN mail_message msg ON msg.id = rel.message_id
                         WHERE m.id = ANY(%%s)
                           AND (m.seen_message_id IS NULL
                                OR m.seen_message_id < msg.id)
                           AND msg.message_type != 'user_notification'
                           AND (msg.author_id IS NULL
                                OR m.partner_id IS NULL
                                OR msg.author_id != m.partner_id)
                           AND (msg.subtype_id IS NULL
                                OR msg.subtype_id != %%s)
                           AND (msg.message_type != 'notification'
                                OR msg.subtype_id = %%s)
                       ) AS unread_messages
                 GROUP BY member_id
                """ % STREAM_REL_TABLE,
                (list(self.ids), change_subtype_id,
                 list(self.ids), change_subtype_id, activity_subtype_id))
            for member_id, counter in self.env.cr.fetchall():
                res[member_id] = counter
        for member in self:
            member.message_unread_counter = res.get(member._origin.id, 0)

    # ------------------------------------------------------------
    # ПРОЧТЕНИЕ (§5.7, §8.3)
    # ------------------------------------------------------------

    def _mark_as_read(self, last_message_id):
        """Как в ядре, но последнее сообщение ищется и среди проекций."""
        self.ensure_one()
        channel = self.channel_id
        if not channel.channel_kind:
            return super()._mark_as_read(last_message_id)
        domain = channel._streams_message_domain()
        if last_message_id:
            domain &= Domain('id', '<=', last_message_id)
        last_message = self.env['mail.message'].search(
            domain, order='id DESC', limit=1)
        if not last_message:
            return
        self._set_last_seen_message(last_message)
        self._set_new_message_separator(last_message.id + 1)
