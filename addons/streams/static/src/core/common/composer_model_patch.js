import { fields } from "@mail/core/common/record";
import { Composer } from "@mail/core/common/composer_model";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    setup() {
        super.setup(...arguments);
        /**
         * Режим композера канала записи: заметка вместо комментария (C3).
         *
         * Живёт на записи Composer, а не в state компонента, потому что
         * идентификатор Composer — сам тред (`static id = OR("thread",
         * "message")`): выбранный режим переживает переключение каналов и
         * перемонтирование композера, как и набранный текст.
         *
         * @type {boolean}
         */
        this.streamsIsNote = fields.Attr(false);
    },
});
