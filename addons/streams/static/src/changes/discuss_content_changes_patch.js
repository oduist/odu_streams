import { StreamsChangesFeed } from "@streams/changes/streams_changes_feed";

import { DiscussContent } from "@mail/core/public_web/discuss_content";

/**
 * Регистрация ленты Changes как подкомпонента контента Discuss.
 *
 * Шаблон подменяется отдельным файлом
 * (`discuss_content_changes_patch.xml`), но OWL ищет компонент в
 * `static components` того класса, чей шаблон его упоминает, — отсюда
 * это присваивание. Через spread, чтобы не затереть чужие регистрации:
 * тот же приём применяют ядровые патчи (`mail/.../message_patch.js`).
 */
DiscussContent.components = { ...DiscussContent.components, StreamsChangesFeed };
