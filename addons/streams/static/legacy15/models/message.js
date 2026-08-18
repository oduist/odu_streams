/** @odoo-module **/

import {
    registerClassPatchModel,
    registerFieldPatchModel,
    registerInstancePatchModel,
} from '@mail/model/model_core';
import { attr, many2many } from '@mail/model/model_field';
import { insertAndReplace, replace, unlinkAll } from '@mail/model/model_field_command';

const PATCH_ID = 'streams/static/src/models/message.js';

registerFieldPatchModel('mail.message', PATCH_ID, {
    /**
     * Каналы записей, в ленте которых сообщение показывается проекцией.
     * Приходит из `_message_format` ключом `stream_channel_ids`.
     */
    streamChannels: many2many('mail.thread'),
    /**
     * Поток сообщения: comment / note / message / change / activity либо
     * undefined для служебных сообщений («прочее»).
     */
    streamsKind: attr(),
});

registerClassPatchModel('mail.message', PATCH_ID, {
    /**
     * @override
     */
    convertData(data) {
        const data2 = this._super(data);
        if ('streams_kind' in data) {
            data2.streamsKind = data.streams_kind || undefined;
        }
        if ('stream_channel_ids' in data) {
            const channelIds = data.stream_channel_ids || [];
            data2.streamChannels = channelIds.length
                ? insertAndReplace(channelIds.map(
                    id => ({ id, model: 'mail.channel' })))
                : unlinkAll();
        }
        return data2;
    },
});

registerInstancePatchModel('mail.message', PATCH_ID, {
    /**
     * Упоминание подсвечивается и в канале-проекции: originThread у такого
     * сообщения — сама запись, а не канал, и ядровая проверка его теряет.
     *
     * @override
     */
    _computeIsHighlighted() {
        if (this.isCurrentPartnerMentioned && this.streamChannels.length > 0) {
            return true;
        }
        return this._super();
    },
    /**
     * Единственный источник принадлежности сообщения тредам — этот
     * computed: `mail.thread.messages` — его readonly-инверсия, а кэш
     * треда вычищает всё, чего нет в `thread.messages`. Без проекций
     * серверная лента канала на клиент просто не доедет.
     *
     * @override
     */
    _computeThreads() {
        const command = this._super();
        const threads = command && command.value ? [...command.value] : [];
        for (const channel of this.streamChannels) {
            if (!threads.includes(channel)) {
                threads.push(channel);
            }
        }
        return replace(threads);
    },
});
