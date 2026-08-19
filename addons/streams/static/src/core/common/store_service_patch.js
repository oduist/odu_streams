import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

/**
 * Поля треда, из которых ядро подмешивает получателей в `partner_ids`.
 * Гасим ровно их, ничего больше.
 */
const RECIPIENT_FIELDS = ["suggestedRecipients", "additionalRecipients"];

/**
 * Тред, у которого нет предложенных получателей.
 *
 * Прокси, а не правка полей самого треда: `suggestedRecipients` —
 * реактивное поле Record, временная подмена значения дёрнула бы всех
 * подписчиков и оставила бы гонку при параллельной отправке.
 *
 * @param {import("models").Thread} thread
 */
function withoutRecipients(thread) {
    return new Proxy(thread, {
        get(target, property, receiver) {
            if (RECIPIENT_FIELDS.includes(property)) {
                return [];
            }
            // получатель — сам target, иначе геттеры ядра потеряют `this`
            const value = Reflect.get(target, property, target);
            return typeof value === "function" ? value.bind(target) : value;
        },
    });
}

patch(Store.prototype, {
    /**
     * Никакой автоматической внешней рассылки (инвариант модуля, §7 ТЗ).
     *
     * Ядровый `getMessagePostParams` при `!isNote` подмешивает в
     * `partner_ids` (и в `partner_emails`) всех `thread.suggestedRecipients`
     * и `thread.additionalRecipients` — то есть отправляет письмо клиенту
     * на каждый внутренний комментарий. Для записей streams это прямое
     * нарушение: внешняя переписка идёт только явно, полным композером
     * (поток `message`, кнопка Send Message).
     *
     * Упоминания (@mention) при этом продолжают работать: ядро кладёт их в
     * `partner_ids` из `getMentionsFromText`, до подмешивания получателей,
     * и этот путь мы не трогаем.
     */
    async getMessagePostParams({ thread }) {
        if (!thread || !this.streamsSuppressesRecipients(thread)) {
            return super.getMessagePostParams(...arguments);
        }
        return super.getMessagePostParams({
            ...arguments[0],
            thread: withoutRecipients(thread),
        });
    },

    /**
     * Нужно ли глушить автоподстановку получателей для этого треда.
     *
     * Все чаттеры записей и наши каналы записей — да; обычные каналы и
     * личные чаты Discuss — нет (там `suggestedRecipients` и так пуст, но
     * лезть в чужую механику незачем).
     *
     * @param {import("models").Thread} thread
     */
    streamsSuppressesRecipients(thread) {
        if (thread.model === "discuss.channel") {
            return thread.channel_kind === "record";
        }
        // чаттер записи: mail.thread-тред любой модели
        return Boolean(thread.model) && thread.model !== "mail.box";
    },
});
