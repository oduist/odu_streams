# -*- encoding: utf-8 -*-
"""Данные треда карточки контакта для клиента (§18.2, Р11)."""
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _thread_to_store(self, store, fields, *, request_list=None):
        """Ключ `streams_company_scope_available` для переключателя охвата.

        Штатный Store треда `parent_id`/`commercial_partner_id` не
        отдаёт (`mail/models/res_partner.py:282-295` — это данные
        партнёра-автора, а не треда), поэтому признак «у контакта есть
        организация или дочерние контакты» кладётся сюда: клиенту нужен
        только факт «показывать ли кнопку Company», сам охват считает
        сервер.

        Ключ добавляется только на запрос данных треда (`request_list`),
        как ядро делает с `hasReadAccess`: `store.add(..., as_thread=True)`
        повторно входит в этот же метод, и безусловная добавка дала бы
        бесконечную рекурсию. Заодно карточка контакта не считает
        дочерние контакты при каждой отдаче сообщения-автора.
        """
        super()._thread_to_store(store, fields, request_list=request_list)
        if request_list is None:
            return
        for partner in self:
            store.add(
                partner,
                {'streams_company_scope_available':
                    partner._streams_company_scope_available()},
                as_thread=True)

    def _streams_company_scope_available(self):
        """Есть ли у контакта организация или дочерние контакты.

        Без sudo: если дочерние контакты пользователю не видны, охват
        Company ему ничего и не покажет.
        """
        self.ensure_one()
        if self.commercial_partner_id and self.commercial_partner_id != self:
            return True
        return bool(self.env['res.partner'].search_count(
            [('parent_id', '=', self.id)], limit=1))
