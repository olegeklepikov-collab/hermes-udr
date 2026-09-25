# Hermes UDR — исследовательское ядро 0.44.0b1 / Research core 0.44.0b1

## Русский

**Интеграция с основанием:** добавлены отдельный режим `foundation`, настройка рабочего каталога, ссылки на контекст запуска, получение исходных файлов без локального разбора и пакет передачи `ResearchHandoffV1`. В этом режиме работа идёт через инструменты существующего сеанса Hermes; автономный CLI не запускается. Импортёр и каноническая приёмка принадлежат основанию и требуют отдельной реализации. См. `skills/research/references/foundation-integration.md`.

Эта редакция заменяет основной маршрут r153, который ограничивал Deep 16 источниками и Ultra 32 источниками и мог отвергать собственный план до поиска. Это эксплуатационная бета; подпись поставки и проверенная область описаны в отдельном манифесте выпуска. Предметная квалификация всех режимов не подразумевается.

**Основной путь:** один штатный агент Hermes → рабочая номенклатура знаний и исследовательская дорожная карта → параллельные задания встроенным агентам → полный сохраняемый корпус → предметный анализ и сопоставление → содержательный отчёт с источниками.

**Пересмотр инструментария:** рассмотрены все 147 прежних регистраций и реализации. Основной интерфейс содержит девять инструментов, включая `research_method` для доступа по имени к 17 базовым и 61 дополнительной специализированной операции. Дополнительный каталог раскрывается по тематическим группам; сетевой диагностический пробник в него не включён. На запрос загружаются назначение, схема и ограничения выбранного метода; все методы не вызываются подряд. Вычисления, компиляция запросов, проверки предоставленных записей и предметное исследование явно различаются. Остальные полезные специализированные модули сохранены в библиотеке.

**Методологическое исполнение:** выбор основания и методов, карта понятий и их операционализация, декомпозиция в атомарные шаги, выдача заданий с зависимостями, сохранённые результаты, научный/деловой профиль поиска и анализа, нарратив реальных поисковых событий и адресные исследовательские циклы. Конкурирующие определения и позиции сохраняются; одинаковая структура не означает одинакового обоснования. Полный парадигмальный разбор применяется там, где он меняет постановку или вывод.

**Методические руководства:** `skills/research/references/decomposition.md`, `knowledge-foundations.md`, `evidence-methods.md`, `search-narrative-loops.md`. Их можно читать через `research_method(action="guide")`; доступны названия `decomposition`, `foundations`, `evidence`, `search_loops`. Для запуска атомарных заданий служат `research_workspace` с действиями `plan`, `dispatch`, `complete_step`; для поисковых/аналитических событий — `record`. Штатные веб-вызовы CLI дополнительно фиксируются автоматически; остальные события явно отмечают источник записи.


**Изменённое поведение:** нет фиксированного числа источников, страниц или модельных вызовов по названию режима. Сотни источников допустимы. Параллельные агенты сохраняют материалы в общий корпус; повтор одного и того же материала не создаёт дубликат. Длинные тексты сохраняются полностью и читаются частями. План уточняется между волнами. Необычный термин, неудачный источник или неполная классификация не блокируют весь процесс.

**Сохранено:** происхождение материала, точные исходные тексты и их хеши, явное различие аннотации/фрагмента/полного текста, ссылки на источники, история плана и отчётов, ограничения доступа и полномочий. Проверка существования ссылки не объявляется проверкой смысла. Предметная проверка центральных выводов — работа исследующих агентов, её нельзя заменить JSON-контрактом.

**Планирование:** сначала карта профильных, смежных и междисциплинарных знаний и применимых методов/стандартов; затем направления, инициативы, волны, фазы, стадии и атомарные шаги там, где уровни имеют отдельный смысл. Каждый шаг имеет вопрос, вход, метод, выход и зависимости. Пустые уровни не создаются. Независимые направления исполняются встроенным `delegate_task` без рекурсивных подагентов.

**Зависимости:** установите `pdfplumber==0.11.9` в то же окружение Python, где установлен Hermes: `python -m pip install pdfplumber==0.11.9`. При наличии `pdftotext` используется он; иначе PDF читается постранично через pdfplumber. Извлечение текста не подтверждает прочтение изображений и диаграмм.

**Запуск:** `python skills/research/scripts/run_research.py --question "..." --mode ultra` в окружении настроенного Hermes. Класс модели берётся из существующей конфигурации; `--model-class` переопределяет выбор. `--max-iterations` и `--max-seconds` задают явные ограничения запуска. Нулевой код означает сохранённый завершённый результат с источниками; неполный результат возвращает 3, ошибка или отсутствие результата — 2. Существующую работу можно продолжить через `--resume-run`. Полные пути сообщает программа. Расходы провайдера не превращаются в вымышленный долларовый предел; оператор контролирует разрешённые расходы через свои настройки и условия задания.

**Ограничения подтверждения:** испытание хранения сотен материалов проверяет ёмкость и параллельную запись, а не научную полноту. Работающий пример не доказывает пригодность для любой темы. Качество результата оценивается по ответу на вопрос, прочитанным первичным материалам, воспроизводимости сравнений, учёту противоречий и обоснованности выводов.

## English

**Foundation integration:** an opt-in `foundation` mode adds an instance-owned workspace, non-authoritative host references, raw-only acquisition and `ResearchHandoffV1` draft export. Use tools in the existing Hermes session; the standalone CLI refuses managed runs. Host intake/import and canonical acceptance require a separate Foundation implementation and qualification. See `skills/research/references/foundation-integration.md`.

This working revision replaces r153's default route, whose fixed 16-source Deep and 32-source Ultra allowances could reject its own plan before searching. This is an operational beta; the release manifest describes signatures and tested scope. General scientific qualification is not implied.

The default path is one native Hermes agent, an interdisciplinary knowledge map and executable roadmap, parallel native leaf agents, a shared full-text corpus, substantive comparative analysis, and a cited report. Nine entrypoints replace the 147-tool default interface; `research_method` progressively exposes 17 primary and 61 optional reviewed library operations, grouped for targeted discovery with their exact input schemas and limitations. Research framing, justified method selection, paradigm/construct relationships, executable work packets, source-quality analysis and search/loop narratives are integrated. Calculations and checks on submitted records are distinguished from source reading and substantive reasoning. Other specialist code remains in the library, outside a universal admission chain.

No canned per-mode source, page or model-call ceiling applies. Hundreds of sources are supported; concurrency is controlled by Hermes, and explicit execution limits can be supplied. Text is preserved without truncation, original evidence remains addressable, and prior plans/reports survive revisions. Citation structure never certifies semantic support. Consequential claims must be checked against actual passages, context and methods by the research agents.

Install the declared `pdfplumber==0.11.9` dependency in the same Python environment as Hermes. PDF extraction uses `pdftotext` when available, otherwise pdfplumber reads every page; image/figure interpretation is separate.

Run `python skills/research/scripts/run_research.py --question "..." --mode ultra` in the configured Hermes environment. Model classes use the existing configuration; optional `--model-class`, `--max-iterations`, `--max-seconds` and `--resume-run` control the run. Exit 0 means a saved complete result with cited sources; 3 means a partial result; 2 means failure or no usable result. User-approved expenditure and access restrictions still apply.

Roadmaps connect streams, initiatives, waves, phases, stages and atomic steps where each level carries meaning; no ceremonial empty hierarchy is required. Parallel workers share a corpus, keep task-specific context, and do not recursively delegate. Cross-stream integration and targeted adversarial examination occur between waves.

Capacity tests are not scientific benchmarks. Judge the actual research answer, primary-source reading, comparisons, contradictions, remaining gaps and warranted conclusions.


## Пять режимов и открытый набор подключений / Five modes and open connectors

Режим `research` добавлен между `search` и `deep`. Глубина каждого режима передаётся в план и задания; количества источников не ограничены названием режима. Подключённые инструменты Hermes и их режимы обнаруживаются по конфигурации плагинов/MCP; перечень поставщиков открыт. Подробнее: `skills/research/references/modes-and-tools.md`.

The new `research` mode selects structured multi-source preliminary analysis. Configured Hermes plugin/MCP tools and their declared modes are discovered dynamically before agent construction; no vendor allowlist is required. See `skills/research/references/modes-and-tools.md`.
