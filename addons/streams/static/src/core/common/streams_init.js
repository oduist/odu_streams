import { fields } from "@mail/core/common/record";
import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

/**
 * Стартовый payload подсистемы Notify (E1 отчёта legacy).
 *
 * В 15 он приезжал полем `data.streams_notify` ответа `init_messaging`; в
 * 19 сервер кладёт его глобальным значением Store
 * (`models/res_users.py:_init_messaging` → `store.add_global_values(
 * streams_notify=...)`), а `Store.add_global_values` на клиенте — это
 * поля синглтона `Store` (`mail/tools/discuss.py:add_global_values`).
 *
 * Поле объявляется, чтобы получить `onUpdate`: `/mail/data` приходит
 * асинхронно и почти наверняка позже старта сервисов, поэтому забирать
 * значение «однажды при старте» нельзя. Симметрично `streams.core` сам
 * читает `store.streams_notify` в своём `setup()` — на случай обратного
 * порядка.
 */
patch(Store.prototype, {
    setup() {
        super.setup(...arguments);
        /**
         * @type {{counter: number, channel_id: number|false,
         *         default_timeout: number, pending: Object[]}|false}
         */
        this.streams_notify = fields.Attr(false, {
            onUpdate() {
                // `onUpdate` вызывается в том числе при создании самой
                // записи Store — тогда ни `env`, ни сервисы ещё не готовы;
                // сервис прочитает значение сам в своём `setup()`
                this.store.env?.services?.["streams.core"]?.applyInitPayload(
                    this.streams_notify
                );
            },
        });
    },
});
