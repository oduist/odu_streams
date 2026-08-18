/** @odoo-module **/

/**
 * Потоки канала записи и их фильтры отображения (§6 ТЗ).
 *
 * Дефолты повторяют серверные `STREAMS_FILTER_DEFAULTS`: клиент рисует
 * ленту до того, как приедет `channel_info`, и обязан знать их сам.
 */
export const STREAMS_FILTER_DEFAULTS = {
    activity: true,
    change: false,
    comment: true,
    message: true,
    note: true,
};

/**
 * Порядок кнопок-тумблеров в шапке канала. Ярлыки переводятся на месте
 * использования, чтобы не тащить сюда окружение.
 */
export const STREAMS_FILTER_ORDER = [
    'comment',
    'note',
    'message',
    'change',
    'activity',
];
