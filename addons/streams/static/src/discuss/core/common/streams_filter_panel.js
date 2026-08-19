import {
    STREAMS_FILTER_DEFAULTS,
    STREAMS_FILTER_ORDER,
} from "@streams/core/common/thread_model_patch";

import { ActionPanel } from "@mail/discuss/core/common/action_panel";

import { Component } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";

/**
 * Панель фильтров потоков в шапке канала записи (§6, A6).
 *
 * Пять тумблеров в порядке `STREAMS_FILTER_ORDER`. Фильтрация серверная
 * (решение Р1 фазы 8), поэтому клик только зовёт `thread.streamsSetFilters`:
 * оптимистичный апдейт, RPC и перечитка ленты — уже внутри него.
 */
export class StreamsFilterPanel extends Component {
    static template = "streams.FilterPanel";
    static components = { ActionPanel };
    static props = ["thread"];

    /** Ярлыки тумблеров — как в клиенте 15. */
    get labels() {
        return {
            activity: _t("Activities"),
            change: _t("Changes"),
            comment: _t("Comments"),
            message: _t("Customers"),
            note: _t("Notes"),
        };
    }

    get filters() {
        // дефолты подмешиваются на случай канала, чьи `streams_filters`
        // ещё не приехали (или приехали неполными — сервер шлёт только
        // то, что знает)
        const active = { ...STREAMS_FILTER_DEFAULTS, ...(this.props.thread.streams_filters ?? {}) };
        const labels = this.labels;
        return STREAMS_FILTER_ORDER.map((key) => ({
            key,
            label: labels[key],
            active: active[key] !== false,
        }));
    }

    /** @param {{key: string, active: boolean}} filter */
    onClickFilter(filter) {
        this.props.thread.streamsSetFilters({ [filter.key]: !filter.active });
    }
}
