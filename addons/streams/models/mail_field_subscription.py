# -*- encoding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

# Служебные поля, на которые подписываться бессмысленно (§8.1). Поля с
# `groups=` отфильтрует сам `fields_get`: он не возвращает то, к чему у
# пользователя нет доступа.
STREAMS_FIELD_EXCLUDE = frozenset({
    'id',
    'display_name',
    '__last_update',
    'access_token',
    'access_url',
    'access_warning',
})
STREAMS_FIELD_EXCLUDE_PREFIXES = (
    'message_',
    'activity_',
    'website_message_',
    'rating_',
    'create_',
    'write_',
)


class MailFieldSubscription(models.Model):
    """Персональная подписка на изменения полей конкретной записи (§4.3, §8.1).

    Подписка не связана с участием в канале записи: подписаться можно на
    любую доступную запись, а участник канала не подписан ни на одно поле,
    пока не выберет их явно.
    """
    _name = 'mail.field.subscription'
    _description = 'Record Field Subscription'
    _rec_name = 'res_model'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, index=True,
        ondelete='cascade', default=lambda self: self.env.user)
    res_model = fields.Char(
        string='Related Document Model', required=True, index=True)
    res_id = fields.Integer(
        string='Related Document ID', required=True, index=True)
    field_ids = fields.Many2many(
        'ir.model.fields', 'mail_field_subscription_field_rel',
        'subscription_id', 'field_id', string='Tracked Fields')

    # имена SQL-объектов совпадают со старыми (`{таблица}_{имя атрибута
    # без подчёркивания}`), поэтому миграции индексов не требуется
    _streams_subscription_uniq = models.Constraint(
        'unique(user_id, res_model, res_id)',
        'A user can subscribe to a record only once.')
    # индекс по записи-источнику: маршрутизация изменений ищет подписки
    # именно по (res_model, res_id), а не по пользователю
    _record_idx = models.Index('(res_model, res_id)')

    # ------------------------------------------------------------
    # ПОИСК
    # ------------------------------------------------------------

    @api.model
    def _streams_find(self, res_model, res_id, user=None):
        """Подписка пользователя на конкретную запись."""
        user = user or self.env.user
        return self.sudo().search([
            ('user_id', '=', user.id),
            ('res_model', '=', res_model),
            ('res_id', '=', res_id),
        ], limit=1)

    @api.model
    def _streams_find_by_targets(self, targets, user=None):
        """Подписки на набор записей одним запросом.

        `targets` — словарь {res_model: множество res_id}. Ходовой путь
        маршрутизации изменений: один search вместо запроса на запись.
        """
        targets = {
            res_model: list(res_ids)
            for res_model, res_ids in (targets or {}).items() if res_ids
        }
        if not targets:
            return self.browse()
        domain = Domain.OR([
            Domain('res_model', '=', res_model) & Domain('res_id', 'in', res_ids)
            for res_model, res_ids in targets.items()
        ])
        if user is not None:
            domain &= Domain('user_id', '=', user.id)
        return self.sudo().search(domain)

    # ------------------------------------------------------------
    # ДОСТУПНЫЕ ПОЛЯ
    # ------------------------------------------------------------

    @api.model
    def _streams_accessible_field_names(self, res_model):
        """Имена полей модели, которые текущий пользователь может читать.

        `fields_get` сам отбрасывает поля с `groups=`, к которым доступа
        нет (`field.groups and not env.su`), поэтому своей проверки групп
        не нужно — но вызывать его надо реальным пользователем, а не под
        sudo, иначе фильтр не сработает.
        """
        if res_model not in self.env:
            return set()
        model = self.env[res_model].sudo(False)
        return set(model.fields_get(attributes=['string']))

    @api.model
    def _streams_available_fields(self, res_model):
        """Поля модели, на которые пользователь вправе подписаться (§8.1).

        Из списка убираем служебное (чаттер, активности, аудит) и поля без
        хранения, у которых нет трекинга: ядровый `_mail_track` читает
        колонку, так что нехранимое поле изменения породить не может и в
        диалоге только мешает.
        """
        names = self._streams_accessible_field_names(res_model)
        if not names:
            return self.env['ir.model.fields'].browse()
        names = {
            name for name in names
            if name not in STREAMS_FIELD_EXCLUDE
            and not name.startswith(STREAMS_FIELD_EXCLUDE_PREFIXES)
        }
        fields_records = self.env['ir.model.fields'].sudo().search([
            ('model', '=', res_model),
            ('name', 'in', list(names)),
        ], order='field_description, name')
        return fields_records.filtered(
            lambda field: field.store or field.tracking)

    # ------------------------------------------------------------
    # ЗАПИСЬ
    # ------------------------------------------------------------

    @api.model
    def _streams_upsert(self, res_model, res_id, field_ids, user=None):
        """Создать/обновить/снять подписку пользователя (§8.1).

        Пустой список полей = отписка: запись подписки удаляется, чтобы
        «подписан на ничего» и «не подписан» не были двумя разными
        состояниями.
        """
        user = user or self.env.user
        subscription = self._streams_find(res_model, res_id, user=user)
        field_ids = sorted(set(field_ids or []))
        if not field_ids:
            if subscription:
                subscription.sudo().unlink()
            return self.browse()
        if subscription:
            subscription.sudo().write({'field_ids': [(6, 0, field_ids)]})
            return subscription
        return self.sudo().create({
            'user_id': user.id,
            'res_model': res_model,
            'res_id': res_id,
            'field_ids': [(6, 0, field_ids)],
        })
