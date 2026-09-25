# Contributing / Разработка

Keep changes small and tied to a reproducible research or operational failure. Preserve full material and uncertainty; do not replace analysis with mandatory schema ceremonies. Do not add fixed model names, closed provider lists or silent source-count ceilings.

Use the actual Hermes Python environment for integration tests. Standalone core checks need Python 3.11+ and pdfplumber 0.11.9 for the PDF fixture. From the repository root:

```sh
PYTHONPATH=src:. python -B -m unittest discover -s tests -p 'test_research_*.py'
PYTHONPATH=src:. python -B -m unittest tests.test_run_research tests.test_native_audit
```

The configuration integration test needs the pinned Hermes modules on PYTHONPATH. Foundation tests use its src plus Research src, run from components/foundation; local Dolt tests need the Dolt executable. Real provider/service tests are separate from mocks and must report their exact scope. Never run them against an active user instance by default.

Research bundles are built by scripts/build_plugin_bundle.py and audited by scripts/audit_native_bundle.py. Foundation's builder requires a clean Git tree and records its exact commit. Sign only verified immutable archives; never commit private keys, live configuration, auth files, databases, transcripts or operational snapshots.

Изменения должны исправлять воспроизводимую исследовательскую или эксплуатационную проблему. Сохраняйте материал и неопределённость; не подменяйте анализ обязательным заполнением схем. Не добавляйте фиксированные модели, закрытые списки поставщиков и скрытые ограничения числа источников.

Интеграционные проверки выполняются в окружении закреплённого Hermes; настоящие сервисы проверяются отдельно от подмен. Не используйте действующий экземпляр пользователя по умолчанию. В коммиты не входят ключи, рабочие настройки, базы, переписки и эксплуатационные снимки. Подписывается только проверенный неизменный архив.
