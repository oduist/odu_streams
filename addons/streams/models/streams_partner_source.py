# -*- encoding: utf-8 -*-
"""Реестр связей «модель → поле-ссылка на партнёра» (§18.3) и SQL VIEW ленты.

Виртуальный чаттер партнёра (§18) — это ещё одна проекция тех же
`mail.message`: сообщения не копируются и не переносятся, агрегация живёт
только в домене выборки. Какие записи считаются «связанными с
контрагентом», описывает этот реестр, а не автоматическое сканирование
m2o-полей: значительная часть таких полей означает не контрагента (нашу
компанию, лабораторию, таможенный пост).

Хранилище агрегата — обычный SQL VIEW `streams_partner_message`
(решение Р1 фазы 9), собираемый из активных строк реестра. Модель ORM на
вьюху не заводится: её потребляет домен `Domain('id','in', SQL(...))`,
поэтому ACL, пагинация и счётчики достаются от ядра (Р3).
"""
import hashlib
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import sql as sql_tools
from odoo.tools.sql import SQL

_logger = logging.getLogger(__name__)

# Имя физической вьюхи. ORM-модели у неё нет, поэтому имя — константа,
# общая для генератора (здесь) и потребителя (`mail.message`).
STREAMS_PARTNER_VIEW = 'streams_partner_message'

# Параметр с сигнатурой (хешем) действующего определения вьюхи: по нему
# `_register_hook` понимает, что вьюху надо пересобрать — реестр
# изменился, модуль-источник установили или сняли, вьюху снесло каскадом
# (Р10, риск 3 отчёта core).
STREAMS_PARTNER_VIEW_SIGNATURE = 'streams.partner_view_signature'

# Уже посеянные пары «модель.поле»: сид отрабатывает по паре один раз,
# иначе удалённую администратором строку воскрешала бы перезагрузка
# реестра.
STREAMS_PARTNER_SEEDED = 'streams.partner_sources_seeded'

# Начальное наполнение реестра (§18.3). Применяется идемпотентно в
# `init()` и только для установленных моделей: XML-data с `ref` на
# `ir.model` чужого модуля упала бы, а зависеть от sale/crm модуль не
# должен и не будет (Р9).
STREAMS_PARTNER_SOURCE_DEFAULTS = {
    'crm.lead': ['partner_id'],
    'sale.order': ['partner_id'],
    'purchase.order': ['partner_id'],
    'account.move': ['partner_id'],
    'stock.picking': ['partner_id'],
    'project.task': ['partner_id'],
}


class StreamsPartnerSource(models.Model):
    """Строка реестра: модель-источник и её поле-ссылка на контрагента.

    Одна строка = одна ветка `UNION ALL` во вьюхе. Деактивация строки
    (`active=False`) убирает ветку из вьюхи, но сохраняет решение
    администратора — поэтому сид никогда не воскрешает архивные строки.
    """
    _name = 'streams.partner.source'
    _description = 'Partner Feed Source'
    _order = 'model_id, field_id'

    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, index=True,
        ondelete='cascade')
    field_id = fields.Many2one(
        'ir.model.fields', string='Partner Field', required=True,
        ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', '=', 'many2one'),"
               " ('relation', '=', 'res.partner'), ('store', '=', True)]")
    model_name = fields.Char(
        related='model_id.model', string='Model Name', store=False)
    field_name = fields.Char(
        related='field_id.name', string='Field Name', store=False)
    active = fields.Boolean(default=True)

    _streams_source_uniq = models.Constraint(
        'unique(model_id, field_id)',
        'This model/field pair is already registered as a partner source.')

    @api.depends('model_id.model', 'field_id.name')
    def _compute_display_name(self):
        for source in self:
            source.display_name = '%s.%s' % (
                source.model_id.model or '', source.field_id.name or '')

    # ------------------------------------------------------------
    # ВАЛИДАЦИЯ (§7.2 отчёта core)
    # ------------------------------------------------------------

    @api.constrains('model_id', 'field_id')
    def _streams_check_source(self):
        """Ветка SQL возможна только для хранимого m2o на res.partner.

        Нехранимое поле колонки не имеет, абстрактная модель и модель с
        `_table_query` — таблицы, поэтому такие строки реестра
        отсекаются на записи, а не молча выпадают из вьюхи.
        """
        for source in self:
            field = source.field_id
            if field.model_id != source.model_id:
                raise ValidationError(_(
                    'Field %(field)s does not belong to model %(model)s.',
                    field=field.name, model=source.model_id.model))
            model = self.env.get(source.model_id.model)
            if model is None:
                raise ValidationError(_(
                    'Model %s is not present in the registry.',
                    source.model_id.model))
            if model._abstract or model._transient or not model._auto:
                raise ValidationError(_(
                    'Model %s has no physical table and cannot be aggregated.',
                    source.model_id.model))
            if not isinstance(model, self.env.registry['mail.thread']):
                raise ValidationError(_(
                    'Model %s has no chatter (mail.thread) and carries no'
                    ' messages.', source.model_id.model))
            if field.ttype != 'many2one' or field.relation != 'res.partner':
                raise ValidationError(_(
                    'Field %s must be a many2one to res.partner.', field.name))
            if not field.store:
                raise ValidationError(_(
                    'Field %s is not stored: it has no SQL column.',
                    field.name))
            if field.name not in model._fields:
                raise ValidationError(_(
                    'Field %(field)s is unknown on model %(model)s.',
                    field=field.name, model=source.model_id.model))

    @api.onchange('field_id')
    def _streams_onchange_field_id(self):
        """Предупреждение (не запрет) о related-зеркале (§7.2).

        Related-поле почти всегда дублирует уже учтённый источник и
        удваивает ленту, но бывают осмысленные исключения — поэтому
        решение остаётся за администратором.
        """
        if self.field_id and self.field_id.related:
            return {'warning': {
                'title': _('Related field'),
                'message': _(
                    'Field %(field)s is related to %(related)s: such a mirror'
                    ' usually duplicates a source that is already registered'
                    ' and doubles the partner feed.',
                    field=self.field_id.name,
                    related=self.field_id.related),
            }}

    # ------------------------------------------------------------
    # CRUD: реестр и вьюха живут одной жизнью
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._streams_rebuild_view()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._streams_rebuild_view()
        return result

    def unlink(self):
        result = super().unlink()
        self._streams_rebuild_view()
        return result

    # ------------------------------------------------------------
    # ЖИЗНЕННЫЙ ЦИКЛ ВЬЮХИ (Р10)
    # ------------------------------------------------------------

    def init(self):
        """Сборка вьюхи на каждом `-u streams` (Р10).

        Сид здесь тоже пробуется, но всерьёз на него рассчитывать
        нельзя: `init()` вызывается в середине загрузки, и модели
        модулей, которые грузятся позже streams (crm, sale), в реестре
        ещё отсутствуют. Настоящий сид — в `_register_hook`.

        По той же причине здесь только гарантируется существование
        вьюхи: пересобирать её на неполном реестре значило бы временно
        выбросить ветки ещё не загруженных моделей. Актуальность
        определения обеспечивает `_register_hook`.
        """
        super().init()
        self._streams_seed_defaults()
        if not self._streams_view_available():
            self._streams_rebuild_view()

    def _register_hook(self):
        """Сид и сверка вьюхи на каждой загрузке реестра (Р9, Р10).

        Момент выбран потому, что реестр моделей здесь уже полон (в
        отличие от `init()`), а сама перезагрузка происходит в том числе
        сразу после установки/деинсталляции модуля-источника — а
        `DROP TABLE ... CASCADE` молча уносит нашу вьюху вместе с
        таблицей. `post_init_hook` не годится вовсе: он вызывается
        только при установке streams.
        """
        super()._register_hook()
        self._streams_seed_defaults()
        self._streams_ensure_view()

    @api.model
    def _streams_ensure_view(self):
        """Пересобрать вьюху, если её нет или определение устарело."""
        definition = self._streams_view_definition()
        signature = self._streams_view_signature(definition)
        stored = self.env['ir.config_parameter'].sudo().get_param(
            STREAMS_PARTNER_VIEW_SIGNATURE)
        if stored == signature and self._streams_view_available():
            return False
        self._streams_rebuild_view(definition=definition)
        return True

    @api.model
    def _streams_view_available(self):
        """Существует ли физическая вьюха (проверка перед выборкой)."""
        return sql_tools.table_kind(
            self.env.cr, STREAMS_PARTNER_VIEW) == sql_tools.TableKind.View

    @api.model
    def _streams_view_signature(self, definition):
        payload = '%s|%s' % (definition.code, definition.params)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @api.model
    def _streams_rebuild_view(self, definition=None):
        """Пересоздать `streams_partner_message` из активных строк реестра."""
        if self.env.context.get('streams_skip_view_rebuild'):
            # массовая правка реестра (сид) пересобирает вьюху один раз
            return
        if definition is None:
            definition = self._streams_view_definition()
        sql_tools.drop_view_if_exists(self.env.cr, STREAMS_PARTNER_VIEW)
        self.env.cr.execute(SQL(
            'CREATE VIEW %s AS (%s)',
            SQL.identifier(STREAMS_PARTNER_VIEW), definition))
        self.env['ir.config_parameter'].sudo().set_param(
            STREAMS_PARTNER_VIEW_SIGNATURE,
            self._streams_view_signature(definition))
        _logger.info(
            'streams: вьюха %s пересобрана', STREAMS_PARTNER_VIEW)

    # ------------------------------------------------------------
    # ГЕНЕРАТОР SQL
    # ------------------------------------------------------------

    @api.model
    def _streams_view_definition(self):
        """`UNION ALL` веток: сам партнёр плюс активные строки реестра.

        Ветка самого партнёра обязательна и не берётся из реестра: без
        неё Related/Company потеряли бы прямую ленту контактов
        организации.
        """
        branches = [self._streams_self_branch_sql()]
        for source in self.sudo().search([]):
            branch = self._streams_branch_sql(
                source.model_id.model, source.field_id.name)
            if branch is not None:
                branches.append(branch)
        return SQL(' UNION ALL ').join(branches)

    @api.model
    def _streams_self_branch_sql(self):
        """Сообщения самой карточки контакта."""
        return SQL(
            'SELECT m.id AS message_id, r.id AS partner_id,'
            ' r.commercial_partner_id AS commercial_partner_id'
            ' FROM mail_message m'
            ' JOIN res_partner r ON m.model = %s AND m.res_id = r.id',
            'res.partner')

    @api.model
    def _streams_branch_sql(self, model_name, field_name):
        """SQL одной ветки реестра или None, если ветка невозможна.

        Метод намеренно не зависит от того, сохранена ли строка реестра:
        тем же кодом считается предпросмотр (§7.4). Идентификаторы
        таблиц и колонок приходят из данных, поэтому подставляются
        исключительно через `SQL.identifier`.
        """
        model = self.env.get(model_name)
        if model is None or model._abstract or model._transient \
                or not model._auto:
            return None
        field = model._fields.get(field_name)
        if field is None or field.type != 'many2one' \
                or field.comodel_name != 'res.partner' \
                or not field.store or not field.column_type:
            return None
        table = model._table
        if not sql_tools.table_exists(self.env.cr, table):
            return None
        if not sql_tools.column_exists(self.env.cr, table, field_name):
            return None
        return SQL(
            'SELECT m.id AS message_id, r.%(field)s AS partner_id,'
            ' p.commercial_partner_id AS commercial_partner_id'
            ' FROM mail_message m'
            ' JOIN %(table)s r ON m.model = %(model)s AND m.res_id = r.id'
            ' JOIN res_partner p ON p.id = r.%(field)s'
            ' WHERE r.%(field)s IS NOT NULL',
            field=SQL.identifier(field_name),
            table=SQL.identifier(table),
            model=model_name)

    @api.model
    def _streams_flush_fields(self):
        """Поля, от которых зависит вьюха: их надо флашить перед выборкой.

        Метаданные `to_flush` едут вместе с SQL внутрь запроса ORM
        (`Environment.flush_query`), поэтому ручного `flush_all` в ленте
        не нужно.

        sudo: читается служебный реестр (метаданные «модель → поле»), а
        не сообщения; портальному пользователю на него прав не выдано,
        но чаттер контакта ему доступен. К выборке ленты это отношения
        не имеет — её по-прежнему фильтрует только `mail.message._search`.
        """
        message = self.env['mail.message']
        partner = self.env['res.partner']
        fields_to_flush = [
            message._fields['model'], message._fields['res_id'],
            partner._fields['commercial_partner_id'],
        ]
        for source in self.sudo().search([]):
            model = self.env.get(source.model_id.model)
            if model is None:
                continue
            field = model._fields.get(source.field_id.name)
            if field is not None:
                fields_to_flush.append(field)
        return fields_to_flush

    # ------------------------------------------------------------
    # ПРЕДПРОСМОТР (§7.4)
    # ------------------------------------------------------------

    def _streams_branch_domain(self):
        """Домен «сообщения, которые добавит эта строка реестра»."""
        self.ensure_one()
        branch = self._streams_branch_sql(
            self.model_id.model, self.field_id.name)
        if branch is None:
            return Domain.FALSE
        return Domain('id', 'in', SQL(
            'SELECT b.message_id FROM (%s) b', branch,
            to_flush=self._streams_flush_fields()))

    def action_preview(self):
        """Сколько сообщений добавит ветка — только число, без содержимого.

        Администратору нужна оценка объёма, поэтому счёт идёт под sudo;
        ни одного сообщения при этом не показывается. Пользователю без
        прав администратора считается его собственная видимость.
        """
        self.ensure_one()
        domain = self._streams_branch_domain()
        message = self.env['mail.message']
        if self.env.user.has_group('base.group_system'):
            message = message.sudo()
        count = message.search_count(domain)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.display_name,
                'message': _('%s messages match this source.', count),
                'type': 'info',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------
    # СИД (Р9)
    # ------------------------------------------------------------

    @api.model
    def _streams_seed_defaults(self):
        """Зарегистрировать дефолтные пары для установленных моделей.

        Каждая пара сеется ровно один раз за жизнь базы: список уже
        посеянного лежит в `ir.config_parameter`. Иначе строку, удалённую
        администратором, воскрешала бы любая перезагрузка реестра —
        а решение «эта ветка нам не нужна» должно быть окончательным
        (архивирование строки работает так же). Пара, чья модель ещё не
        установлена, в список не попадает и будет посеяна позже, когда
        модуль-источник поставят.
        """
        parameters = self.env['ir.config_parameter'].sudo()
        seeded = set(filter(None, (parameters.get_param(
            STREAMS_PARTNER_SEEDED, '') or '').split(',')))
        ir_model = self.env['ir.model']
        ir_model_fields = self.env['ir.model.fields']
        created = self.browse()
        for model_name, field_names in STREAMS_PARTNER_SOURCE_DEFAULTS.items():
            if self.env.get(model_name) is None:
                continue
            for field_name in field_names:
                key = '%s.%s' % (model_name, field_name)
                if key in seeded:
                    continue
                if self._streams_branch_sql(model_name, field_name) is None:
                    continue
                model_record = ir_model._get(model_name)
                field_record = ir_model_fields._get(model_name, field_name)
                if not model_record or not field_record:
                    continue
                exists = self.with_context(active_test=False).search_count([
                    ('model_id', '=', model_record.id),
                    ('field_id', '=', field_record.id),
                ])
                if exists:
                    seeded.add(key)
                    continue
                try:
                    # параллельный старт воркеров может привести к гонке
                    # на уникальном ключе: реестр из-за этого падать не
                    # должен
                    with self.env.cr.savepoint():
                        created |= self.with_context(
                            streams_skip_view_rebuild=True).create({
                                'model_id': model_record.id,
                                'field_id': field_record.id,
                            })
                except Exception:  # noqa: BLE001 - см. комментарий выше
                    _logger.warning(
                        'streams: источник ленты %s не зарегистрирован',
                        key, exc_info=True)
                    continue
                seeded.add(key)
        if created:
            parameters.set_param(
                STREAMS_PARTNER_SEEDED, ','.join(sorted(seeded)))
            _logger.info(
                'streams: в реестр ленты партнёра добавлены источники %s',
                created.mapped('display_name'))
        return created
