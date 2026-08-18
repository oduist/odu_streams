/** @odoo-module **/

import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";
import { link } from "@mail/model/model_field_command";

import { StreamsNotifyContainer } from "@streams/components/streams_notify_popup/streams_notify_popup";
import { StreamsNotifyComposer } from "@streams/components/streams_notify_composer/streams_notify_composer";
import { registerStreamsNotifyService } from "@streams/js/notify_bridge";

const { EventBus } = owl.core;

export const BUS_NEW = 'streams.notify/new';
export const BUS_UPDATE = 'streams.notify/update';
export const BUS_COUNTER = 'streams.notify/counter';

// Отметка «попап показан» шлётся пачкой: за секунду их может прилететь
// несколько, а серверу важен только факт показа.
const POPUP_SHOWN_DELAY = 500;
const DEFAULT_TIMEOUT = 10;

/**
 * Сервис уведомлений (§12).
 *
 * Своим, а не ядровым `notification`: тост в 15 не принимает компонент,
 * его таймаут — константа 4000 мс, а нам нужны произвольный таймаут,
 * стек sticky с переключением, плеер и кнопка Reply внутри карточки.
 * Скелет копирует `web/static/src/core/notifications/notification_service.js`.
 */
export const streamsNotifyService = {
    dependencies: ['action', 'rpc', 'dialog'],

    start(env, { action, rpc, dialog }) {
        const bus = new EventBus();
        const state = {
            counter: 0,
            channelId: false,
            isSoundMuted: false,
            settingsId: false,
            defaultTimeout: DEFAULT_TIMEOUT,
            popups: [],
            stickyIndex: 0,
        };
        const timers = {};
        let shownQueue = [];
        let shownTimer = null;
        let audio = null;

        //------------------------------------------------------------------
        // Вспомогательное
        //------------------------------------------------------------------

        function update() {
            bus.trigger('UPDATE');
        }

        function callNotify(method, args, kwargs) {
            return rpc('/web/dataset/call_kw/mail.notify/' + method, {
                model: 'mail.notify',
                method: method,
                args: args || [],
                kwargs: kwargs || {},
            });
        }

        function stickyPopups() {
            return state.popups.filter(popup => popup.data.is_sticky);
        }

        //------------------------------------------------------------------
        // Стек попапов (§12.4)
        //------------------------------------------------------------------

        function startTimer(id, delay) {
            clearTimer(id);
            timers[id] = browser.setTimeout(() => close(id), delay);
        }

        function clearTimer(id) {
            if (timers[id]) {
                browser.clearTimeout(timers[id]);
                delete timers[id];
            }
        }

        function push(data) {
            if (!data || !data.id) {
                return;
            }
            const known = state.popups.find(popup => popup.id === data.id);
            if (known) {
                known.data = Object.assign({}, known.data, data);
                update();
                return;
            }
            state.popups.push({ id: data.id, data: data });
            if (data.is_sticky) {
                // новый sticky показывается сразу: он и есть самый свежий
                state.stickyIndex = stickyPopups().length - 1;
            } else {
                startTimer(
                    data.id, (data.timeout || DEFAULT_TIMEOUT) * 1000);
            }
            queueShown(data.id);
            playSound();
            update();
        }

        function close(id) {
            clearTimer(id);
            const index = state.popups.findIndex(popup => popup.id === id);
            if (index === -1) {
                return;
            }
            state.popups.splice(index, 1);
            const sticky = stickyPopups();
            if (state.stickyIndex >= sticky.length) {
                state.stickyIndex = Math.max(sticky.length - 1, 0);
            }
            update();
        }

        function closeAll() {
            for (const popup of state.popups.slice()) {
                close(popup.id);
            }
        }

        /**
         * Наведение мыши приостанавливает таймер: попап не должен исчезать
         * из-под курсора, пока его читают.
         */
        function pause(id) {
            clearTimer(id);
        }

        function resume(id) {
            const popup = state.popups.find(entry => entry.id === id);
            if (popup && !popup.data.is_sticky) {
                startTimer(
                    id, (popup.data.timeout || DEFAULT_TIMEOUT) * 1000);
            }
        }

        function showSticky(index) {
            const sticky = stickyPopups();
            if (!sticky.length) {
                return;
            }
            state.stickyIndex = Math.min(Math.max(index, 0), sticky.length - 1);
            update();
        }

        //------------------------------------------------------------------
        // Отметка показа (§12.4: падение вкладки не должно съесть попап)
        //------------------------------------------------------------------

        function queueShown(id) {
            if (!shownQueue.includes(id)) {
                shownQueue.push(id);
            }
            if (shownTimer) {
                browser.clearTimeout(shownTimer);
            }
            shownTimer = browser.setTimeout(flushShown, POPUP_SHOWN_DELAY);
        }

        function flushShown() {
            shownTimer = null;
            const ids = shownQueue;
            shownQueue = [];
            if (!ids.length) {
                return;
            }
            callNotify('streams_notify_popup_shown', [ids]).catch(() => {});
        }

        //------------------------------------------------------------------
        // Звук (§12.4 + персональный Mute)
        //------------------------------------------------------------------

        async function playSound() {
            if (state.isSoundMuted) {
                return;
            }
            const legacyEnv = owl.Component.env;
            const busService = legacyEnv.services && legacyEnv.services.bus_service;
            if (busService && busService.isMasterTab && !busService.isMasterTab()) {
                // три открытые вкладки не должны звонить трижды
                return;
            }
            try {
                const messaging = await legacyEnv.services.messaging.get();
                if (messaging && messaging.soundEffects
                        && messaging.soundEffects.newMessage) {
                    messaging.soundEffects.newMessage.play();
                    return;
                }
            } catch (_error) {
                // messaging ещё не поднят — играем сами, как это делает
                // bus_service._beep()
            }
            if (typeof Audio === 'undefined') {
                return;
            }
            if (!audio) {
                audio = new Audio();
                const extension = audio.canPlayType('audio/ogg; codecs=vorbis')
                    ? '.ogg' : '.mp3';
                audio.src = '/mail/static/src/audio/dm_02' + extension;
            }
            audio.currentTime = 0;
            Promise.resolve(audio.play()).catch(() => {});
        }

        function toggleMute() {
            state.isSoundMuted = !state.isSoundMuted;
            update();
            if (!state.settingsId) {
                return;
            }
            rpc('/web/dataset/call_kw/res.users.settings/set_res_users_settings', {
                model: 'res.users.settings',
                method: 'set_res_users_settings',
                args: [
                    [state.settingsId],
                    { is_streams_notify_sound_muted: state.isSoundMuted },
                ],
                kwargs: {},
            }).catch(() => {});
        }

        //------------------------------------------------------------------
        // Шина
        //------------------------------------------------------------------

        function onNotifications(notifications) {
            for (const notification of notifications) {
                let payload = notification.payload;
                if (typeof payload === 'string') {
                    try {
                        payload = JSON.parse(payload);
                    } catch (_error) {
                        continue;
                    }
                }
                if (notification.type === BUS_NEW) {
                    if ('counter' in payload) {
                        state.counter = payload.counter;
                    }
                    push(payload);
                    bus.trigger('NOTIFY-NEW', payload);
                } else if (notification.type === BUS_UPDATE) {
                    const popup = state.popups.find(
                        entry => entry.id === payload.id);
                    if (popup) {
                        popup.data = Object.assign({}, popup.data, payload);
                    }
                    update();
                    bus.trigger('NOTIFY-UPDATE', payload);
                } else if (notification.type === BUS_COUNTER) {
                    state.counter = payload.counter || 0;
                    update();
                }
            }
        }

        function subscribe() {
            const legacyEnv = owl.Component.env;
            const busService = legacyEnv.services && legacyEnv.services.bus_service;
            if (!busService) {
                return;
            }
            // addChannel идемпотентен: bus_actions подписал этот же канал
            busService.addChannel('bus_actions_' + session.uid);
            busService.onNotification(api, onNotifications);
            busService.startPolling();
        }

        //------------------------------------------------------------------
        // Публичное
        //------------------------------------------------------------------

        function markRead(notifyIds) {
            if (!notifyIds || !notifyIds.length) {
                return Promise.resolve({ counter: state.counter });
            }
            return callNotify('streams_notify_mark_read', [notifyIds]).then(
                result => {
                    state.counter = (result && result.counter) || 0;
                    update();
                    return result;
                });
        }

        function openComposer(options) {
            dialog.add(StreamsNotifyComposer, Object.assign({
                service: api,
            }, options || {}));
        }

        function reply(data) {
            openComposer({
                parentId: data.id,
                parentAuthor: data.author && data.author.name,
                isSticky: data.is_sticky,
                timeout: data.timeout,
            });
        }

        /**
         * Канал заводится лениво, поэтому в момент клика клиент может о нём
         * ещё не знать: он создан после `_init_messaging`. Без вставки в
         * messaging Discuss открывается пустым — active_id не с чем связать.
         * Вставка повторяет ядровый `_initChannels`.
         */
        async function ensureChannelInMessaging(info) {
            const legacyEnv = owl.Component.env;
            if (!legacyEnv.services || !legacyEnv.services.messaging) {
                return undefined;
            }
            const messaging = await legacyEnv.services.messaging.get();
            if (!messaging) {
                return undefined;
            }
            const Thread = messaging.models['mail.thread'];
            const data = Thread.convertData(info);
            if (!data.members && messaging.currentPartner) {
                data.members = link(messaging.currentPartner);
            }
            const channel = Thread.insert(
                Object.assign({ model: 'mail.channel' }, data));
            if (!channel.isPinned) {
                channel.pin();
            }
            return channel;
        }

        async function openChannel() {
            const info = await callNotify('streams_notify_open_channel', []);
            if (!info || !info.id) {
                return;
            }
            state.channelId = info.id;
            const channel = await ensureChannelInMessaging(info);
            if (channel) {
                // openThread сам откроет Discuss, если он ещё не открыт
                await channel.messaging.discuss.openThread(channel);
                return;
            }
            await action.doAction('mail.action_discuss', {
                additionalContext: { active_id: 'mail.channel_' + info.id },
            });
        }

        function openRecord(resModel, resId) {
            if (!resModel || !resId) {
                return;
            }
            action.doAction({
                type: 'ir.actions.act_window',
                res_model: resModel,
                res_id: resId,
                views: [[false, 'form']],
                view_mode: 'form',
            });
        }

        /**
         * Стартовый payload из `_init_messaging` (А9): счётчик, канал и
         * накопившиеся, но ещё не показанные попапы.
         */
        function init(payload) {
            if (!payload) {
                return;
            }
            state.counter = payload.counter || 0;
            state.channelId = payload.channel_id || false;
            state.defaultTimeout = payload.default_timeout || DEFAULT_TIMEOUT;
            for (const item of payload.pending || []) {
                push(item);
            }
            update();
        }

        function initSettings(settings) {
            if (!settings) {
                return;
            }
            state.settingsId = settings.id || false;
            state.isSoundMuted = Boolean(
                settings.is_streams_notify_sound_muted);
            update();
        }

        const api = {
            bus,
            state,
            init,
            initSettings,
            push,
            close,
            closeAll,
            pause,
            resume,
            showSticky,
            stickyPopups,
            markRead,
            openComposer,
            openChannel,
            openRecord,
            reply,
            toggleMute,
            callNotify,
        };

        registry.category('main_components').add('StreamsNotifyContainer', {
            Component: StreamsNotifyContainer,
            props: { bus, state, service: api },
        });

        // подписка после готовности клиента — так надёжнее, чем на старте
        // сервиса (образец jkl_develop/force_reload_service.js)
        env.bus.on('WEB_CLIENT_READY', null, subscribe);

        registerStreamsNotifyService(api);
        return api;
    },
};

registry.category('services').add('streams_notify', streamsNotifyService);
