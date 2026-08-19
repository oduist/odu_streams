import { DiscussContent } from "@mail/core/public_web/discuss_content";

import { StreamsNotifyFeed } from "./streams_notify_feed";

/**
 * Подмена содержимого Discuss для личного канала Notifications (A19).
 *
 * Ядро 19 не знает реестра «свой вид канала» (проверено: категорий
 * `discuss.channel_view` и подобных нет), поэтому используется штатный
 * приём самих ядровых модулей — `t-inherit` шаблона `mail.DiscussContent`
 * (так делают discuss/call и im_livechat). XML-часть — в `.xml` рядом.
 */
Object.assign(DiscussContent.components, { StreamsNotifyFeed });
