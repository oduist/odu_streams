# -*- encoding: utf-8 -*-
import odoo.tests
from odoo.addons.web.tests.test_js import unit_test_error_checker

# Фильтр набора: Hoot строит имя сюиты из пути модуля
# (`web/static/tests/_framework/module_set.hoot.js`, `getSuitePath`), поэтому
# наши файлы `streams/static/tests/*.test.js` живут под `@streams/...`.
# Текстовый фильтр сравнивается с полным именем задачи, так что `streams`
# отбирает ровно наш модуль и не тянет ~10 000 тестов ядра.
STREAMS_HOOT_URL = (
    '/web/tests'
    '?headless&loglevel=2&preset=desktop&timeout=30000&filter=streams'
)


@odoo.tests.tagged('post_install', '-at_install')
class StreamsHootSuite(odoo.tests.HttpCase):
    """Запуск Hoot-набора модуля (`static/tests/**/*.test.js`).

    Обёртка по образцу `web/tests/test_js.py` (`WebSuite.test_unit_desktop`):
    сам по себе `--test-enable` js-тесты не выполняет, их надо открыть
    браузером. Требуется Chrome/Chromium в окружении; без него
    `HttpCase.browser_js` поднимает `SkipTest`.
    """

    @odoo.tests.no_retry
    def test_streams_unit_desktop(self):
        self.browser_js(
            STREAMS_HOOT_URL,
            "",
            "",
            login='admin',
            timeout=1800,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=unit_test_error_checker,
        )
