/** @odoo-module **/

/**
 * Мостик между messaging-моделями (легаси-окружение) и wowl-сервисом
 * уведомлений.
 *
 * Патчи `mail.*` живут в окружении messaging, где wowl-сервисов нет, а
 * тащить туда весь env ради двух вызовов незачем: оба файла лежат в одном
 * бандле, поэтому обычного модульного синглтона достаточно. Очередь нужна
 * потому, что порядок «сервис стартовал» / «клиент проинициализировался»
 * не гарантирован.
 */

let service = null;
const pending = [];

export function registerStreamsNotifyService(api) {
    service = api;
    while (pending.length) {
        pending.shift()(api);
    }
}

export function withStreamsNotifyService(callback) {
    if (service) {
        callback(service);
        return;
    }
    pending.push(callback);
}
