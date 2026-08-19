# -*- encoding: utf-8 -*-
import odoo.tests
from odoo.addons.web.tests.test_js import unit_test_error_checker

# Hoot строит имя сюиты из пути модуля
# (`web/static/tests/_framework/module_set.hoot.js`, `getSuitePath`), поэтому
# наши файлы `streams/static/tests/*.test.js` живут под `@streams/...`.
STREAMS_HOOT_SUITE = '@streams'


def _hoot_job_id(full_name):
    """Id задачи Hoot по её полному имени.

    Тот же хеш считают ядровый `HOOTCommon._generate_hash`
    (`web/tests/test_js.py`) и клиент (`hoot/hoot_utils.js`, `generateHash`).

    Отбор именно по `&id=`, а не по `&filter=`: текстовый фильтр Hoot для
    незакавыченного слова — НЕЧЁТКИЙ (`hoot_utils.js`,
    `QueryPartialString.compareFn = getFuzzyScore`). Слово `streams`
    подсвечивается как подпоследовательность в тысячах ядровых имён
    (`@html_editor/li**s**t/normaliza**t**ion/...`), поэтому `filter=streams`
    запускал весь набор ядра (~10 000 тестов) вместо наших 26.
    """
    value = 0
    for char in full_name:
        value = ((value << 5) - value + ord(char)) & 0xFFFFFFFF
    return '%08x' % value


STREAMS_HOOT_URL = (
    '/web/tests'
    '?headless&loglevel=2&preset=desktop&timeout=30000'
    '&id=%s' % _hoot_job_id(STREAMS_HOOT_SUITE)
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
