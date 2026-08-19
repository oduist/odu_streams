import { models } from "@web/../tests/web_test_helpers";

/**
 * Получатель уведомления и состояние доставки (§4.5).
 *
 * Отдельная mock-модель нужна не ради своих методов, а ради связи:
 * `mail.notify.recipient_ids` — o2m на неё, и mock-сервер молча выкидывает
 * серверные поля, чья модель-получатель не зарегистрирована.
 */
export class MailNotifyRecipient extends models.ServerModel {
    _name = "mail.notify.recipient";
}
