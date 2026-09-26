# Нативная установка Hermes и Ultra Deep Research

Комплект описывает установку на macOS, Linux и Windows без Docker и WSL. Выполняйте команды для своей операционной системы. Каталоги `UDR_SOFTWARE`, `UDR_STATE`, `UDR_SETUP_DIR` и профиль `HERMES_HOME` определяются в [руководстве 01](ru/01-platform-and-hermes.md); остальные руководства используют те же значения.

Основные документы:

1. [Спецификация платформы знаний и работы Hermes](HERMES_KNOWLEDGE_WORK_PLATFORM_SPEC.md) — состав системы, роли компонентов и границы интеграции.
2. [Маршрут от чистой системы до развёртывания](HERMES_ZERO_TO_DEPLOYMENT_ROADMAP.md) — последовательность работ и критерии проверки.
3. [Задание агенту для развёртывания](HERMES_DEPLOYMENT_AGENT_HANDOFF_PROMPT.md) — входные данные, ограничения и ожидаемая передача результата.

Практические руководства:

1. [Основа и Hermes](ru/01-platform-and-hermes.md) — каталоги, системные пакеты, закреплённый Hermes и Research.
2. [SQLite](ru/02-sqlite.md) — нативная установка, проверка и резервное копирование.
3. [AgentMemory](ru/03-agentmemory.md) — установка службы и подключение Hermes.
4. [Graphiti и Neo4j](ru/04-graphiti-neo4j.md) — нативное хранилище графа.
5. [Zvec](ru/05-zvec.md) — локальная векторная библиотека и подключение MCP.
6. [Инженерные средства](ru/06-engineering.md) — Serena, Semgrep, ast-grep и вычислительная среда.
7. [Наблюдаемость](ru/07-observability.md) — OTel Collector и Phoenix.
8. [Автозапуск и восстановление](ru/08-services-and-recovery.md) — службы, сохранение состояния и возврат к работе.
9. [Dolt и Beads](ru/09-dolt-beads.md) — нативные базы и учёт задач.
10. [Research и итоговая проверка](ru/10-research-and-verification.md) — проверка подписанного выпуска и нативного пути.
11. [Mirage](ru/11-mirage.md) — локальный каталог только для чтения через MCP.
