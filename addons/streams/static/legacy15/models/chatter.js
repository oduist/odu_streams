/** @odoo-module **/

import { registerInstancePatchModel } from '@mail/model/model_core';

import { withStreamsNotifyService } from '@streams/js/notify_bridge';

const PATCH_ID = 'streams/static/src/models/chatter.js';

registerInstancePatchModel('mail.chatter', PATCH_ID, {
    /**
     * @override
     */
    _created() {
        // биндинг обязателен, пока OWL не умеет стрелки в обработчиках
        this.onClickStreamsSendMessage = this.onClickStreamsSendMessage.bind(this);
        this.onClickStreamsChanges = this.onClickStreamsChanges.bind(this);
        this.onClickStreamsNotify = this.onClickStreamsNotify.bind(this);
        this.onClickStreamsInvite = this.onClickStreamsInvite.bind(this);
        return this._super();
    },
    /**
     * Приглашение клиента в чат (§9.2, решение 2 от 2026-08-18).
     *
     * Кнопка есть и на записях без канала: приглашение из чаттера канал
     * создаёт — это пятый триггер §5.1. Поэтому знание о наличии канала
     * клиенту не нужно и лишнего RPC на каждой форме не возникает.
     */
    onClickStreamsInvite() {
        const thread = this.thread;
        if (!thread || !thread.id) {
            return;
        }
        this.env.bus.trigger('do-action', {
            action: {
                type: 'ir.actions.act_window',
                name: this.env._t("Invite a customer to this chat"),
                res_model: 'streams.guest.invite.wizard',
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'new',
                res_id: false,
                context: {
                    default_res_model: thread.model,
                    default_res_id: thread.id,
                },
            },
        });
    },
    /**
     * Приоритетное уведомление по записи (§11.1, §12.2): своя форма,
     * ссылка на запись подставляется автоматически.
     */
    onClickStreamsNotify() {
        const thread = this.thread;
        if (!thread || !thread.id) {
            return;
        }
        withStreamsNotifyService(service => service.openComposer({
            resModel: thread.model,
            resId: thread.id,
        }));
    },
    /**
     * Подписка на поля записи (§8.1, §11.1): визард со списком доступных
     * полей. Что доступно и что предотмечено, решает сервер — клиент
     * передаёт только модель и запись.
     */
    onClickStreamsChanges() {
        const thread = this.thread;
        if (!thread || !thread.id) {
            return;
        }
        this.env.bus.trigger('do-action', {
            action: {
                type: 'ir.actions.act_window',
                name: this.env._t("Changes"),
                res_model: 'streams.field.subscription.wizard',
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'new',
                res_id: false,
                context: {
                    default_res_model: thread.model,
                    default_res_id: thread.id,
                },
            },
        });
    },
    /**
     * Внешняя переписка (§11.1): полный композер с подтипом
     * `streams.mt_message`. Свою форму отправки делаем позже, при
     * унификации с кнопками Send Email из velesagro_crm/email_document.
     */
    onClickStreamsSendMessage() {
        const thread = this.thread;
        if (!thread || !thread.id) {
            return;
        }
        this.env.bus.trigger('do-action', {
            action: {
                type: 'ir.actions.act_window',
                name: this.env._t("Send Message"),
                res_model: 'mail.compose.message',
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'new',
                res_id: false,
                context: {
                    default_composition_mode: 'comment',
                    default_is_log: false,
                    default_model: thread.model,
                    default_res_id: thread.id,
                    default_subtype_xmlid: 'streams.mt_message',
                },
            },
            options: {
                on_close: () => {
                    if (!thread.exists()) {
                        return;
                    }
                    thread.loadNewMessages();
                },
            },
        });
    },
});
