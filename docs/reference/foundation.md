# Foundation bridge / Мост Foundation

**EN.** Hermes UDR Foundation 0.13a3 exposes 64 tools and five Hermes hooks. Names below match this candidate's `plugin.yaml` and `plugin.py`. “Assess”, “evaluate”, “verify”, and “get” report on supplied or stored evidence; they do not perform the operation they assess. Write tools change the stated local authority, subject to their request contract. The bridge does not itself provide a complete backup service, scheduler, or research qualification.

**RU.** Hermes UDR Foundation 0.13a3 предоставляет 64 инструмента и пять обработчиков событий Hermes. Имена ниже совпадают с `plugin.yaml` и `plugin.py` этого кандидата. Инструменты проверки и оценки не выполняют проверяемую операцию. Инструменты записи меняют указанное локальное состояние в рамках своего контракта. Мост сам по себе не является готовой службой резервного копирования, планировщиком или подтверждением качества исследований.

**Release / Выпуск:** See the [release manifest](release-manifest.json) for the published component versions, hashes and signature status. / Опубликованные версии, хеши и статус подписи указаны в [манифесте выпуска](release-manifest.json). This working copy precedes signing. / Эта рабочая копия предшествует подписанию.

## Host-only Research integration / Внутренняя интеграция Research

The following Python APIs are **not** among the 64 model-callable tools. / Следующие интерфейсы Python **не входят** в 64 инструмента, доступных модели.

| API | EN | RU |
|---|---|---|
| `ResearchSession.prepare` / `check` | Validate active work contract, claimed Beads task and live lease; obtain scoped AgentMemory and Graphiti context; record and recheck admission. | Проверяют действующий контракт, закреплённую задачу и аренду; получают контекст памяти и графа, записывают и повторно проверяют допуск. |
| `run_in_host` | Use the existing Hermes agent and tools for one research turn; do not start another controller. | Использует существующего агента и инструменты Hermes для одного исследования без второго управляющего процесса. |
| `ResearchSession.restore` | Restore a saved canonical admission for finalization, without rerunning the model. | Восстанавливает сохранённый канонический допуск для завершения без повтора вызова модели. |
| `complete` / `ResearchIntake.ingest` | Verify the immutable `ResearchHandoffV1` package, import bytes and local-ID mapping as `ResearchImportedDraftV1`, then synchronize a draft reference to memory and graph. | Проверяют неизменяемый пакет `ResearchHandoffV1`, импортируют байты и соответствие локальных идентификаторов как `ResearchImportedDraftV1`, затем сохраняют ссылку на черновик в памяти и графе. |

Admission references are not self-authenticating. An imported draft is not accepted evidence, approved claims, release authorization or delivery permission. / Ссылки допуска не удостоверяют себя сами. Импортированный черновик не означает принятия доказательств и тезисов, разрешения выпуска или доставки.

## Bridge, release / Мост, выпуск

| Tool | EN | RU |
|---|---|---|
| `foundation_bridge_migrate` | Apply Foundation storage migrations. | Применяет миграции хранилища Foundation. |
| `foundation_bridge_health` | Read bridge health. | Читает состояние моста. |
| `foundation_release_verify` | Verify release evidence; no publication. | Проверяет данные выпуска; не публикует его. |

## Profiles, transport / Профили, доставка

| Tool | EN | RU |
|---|---|---|
| `foundation_profiles_migrate` | Apply profile-transport migrations. | Применяет миграции профилей и доставки. |
| `foundation_profiles_health` | Read profile-transport health. | Читает состояние профилей и доставки. |
| `foundation_profile_get` | Read a stored profile. | Читает сохранённый профиль. |
| `foundation_handoff_record` | Record a work handoff. | Записывает передачу работы. |
| `foundation_review_position_record` | Record a review position. | Записывает позицию рецензирования. |
| `foundation_operator_effect_record` | Record an operator effect. | Записывает действие оператора. |
| `foundation_checkpoint_resume` | Resume a recorded checkpoint. | Возобновляет зафиксированную контрольную точку. |
| `foundation_merge_assess` | Assess a proposed merge; no merge. | Оценивает объединение; не выполняет его. |
| `foundation_telegram_ingress` | Record Telegram ingress in the transport ledger. | Фиксирует вход Telegram в журнале доставки. |
| `foundation_telegram_media` | Ingest Telegram media metadata/content under the transport contract. | Принимает медиаданные Telegram по контракту доставки. |
| `foundation_delivery_prepare` | Register a delivery intent and idempotency key; no send. | Регистрирует намерение доставки и ключ идемпотентности; не отправляет. |
| `foundation_delivery_reconcile` | Reconcile provider delivery status in the ledger. | Сверяет статус доставки поставщика в журнале. |
| `foundation_delivery_redeliver` | Assess authorization to resend an ambiguous delivery; no send. | Проверяет право повторной доставки при неопределённом исходе; не отправляет. |
| `foundation_telegram_route` | Assess an allowed Telegram route; no connection. | Оценивает допустимость маршрута Telegram; не подключается. |

## Observability, recovery assessment / Наблюдаемость, оценка восстановления

| Tool | EN | RU |
|---|---|---|
| `foundation_observability_migrate` | Apply trace-store migrations. | Применяет миграции хранилища трасс. |
| `foundation_trace_record` | Record a trace event. | Записывает событие трассы. |
| `foundation_trace_reconcile` | Reconcile recorded trace events. | Сверяет записанные события трассы. |
| `foundation_trace_health` | Read trace-store health. | Читает состояние хранилища трасс. |
| `foundation_backup_inventory` | Verify an existing 12-class archive inventory; no backup creation. | Проверяет состав существующей копии из 12 классов; не создаёт копию. |
| `foundation_recovery_objectives` | Evaluate supplied RPO/RTO measurements. | Оценивает переданные измерения RPO/RTO. |
| `foundation_restore_assess` | Assess receipts from an alternate restore; no restore. | Оценивает квитанции отдельного восстановления; не восстанавливает. |
| `foundation_checkpoint_assess` | Assess checkpoint barrier and class receipts; no capture. | Оценивает барьер и квитанции контрольной точки; не создаёт снимок. |

## Authority, runtime gates / Полномочия, проверки исполнения

| Tool | EN | RU |
|---|---|---|
| `foundation_authority_get` | Read the declared single-writer authority map. | Читает объявленную карту единственных писателей. |
| `foundation_runtime_lease` | Acquire or assess a runtime work lease. | Выдаёт или проверяет аренду на выполнение работы. |
| `foundation_outbox_enqueue` | Enqueue an idempotent event; no external send. | Ставит событие в очередь с защитой от повторов; не отправляет наружу. |
| `foundation_effective_runtime_reconcile` | Compare desired and observed runtime, schedules, backups. | Сопоставляет желаемое и наблюдаемое исполнение, расписания и копии. |
| `foundation_failure_suite_assess` | Assess failure-suite evidence. | Оценивает свидетельства набора отказов. |
| `foundation_gate_vector_evaluate` | Evaluate supplied gate results. | Оценивает переданные результаты контрольных условий. |

## Dolt / Dolt

| Tool | EN | RU |
|---|---|---|
| `foundation_dolt_put` | Write a versioned Dolt object. | Записывает версионированный объект Dolt. |
| `foundation_dolt_get` | Read a Dolt object/version. | Читает объект или версию Dolt. |
| `foundation_dolt_sql_health` | Read managed Dolt SQL health. | Читает состояние управляемого Dolt SQL. |

## Artifacts, index / Артефакты, индекс

| Tool | EN | RU |
|---|---|---|
| `foundation_artifact_ingest` | Ingest an artifact into local authority. | Принимает артефакт в локальное хранилище. |
| `foundation_artifact_recover` | Recover incomplete artifact operations. | Восстанавливает незавершённые операции с артефактами. |
| `foundation_artifact_tombstone` | Tombstone an artifact. | Помечает артефакт как удалённый. |
| `foundation_index_migrate` | Apply index migrations. | Применяет миграции индекса. |
| `foundation_index_upsert` | Write/update a source-backed index entry. | Записывает или обновляет запись индекса с исходной опорой. |
| `foundation_index_query` | Query the local index. | Выполняет поиск по локальному индексу. |
| `foundation_index_rebuild` | Rebuild derived index from sources. | Перестраивает производный индекс из исходных данных. |
| `foundation_index_tombstone` | Tombstone an index entry. | Помечает запись индекса как удалённую. |

## Graph / Граф

| Tool | EN | RU |
|---|---|---|
| `foundation_graph_migrate` | Apply graph-store migrations. | Применяет миграции графового хранилища. |
| `foundation_graph_health` | Read graph service health. | Читает состояние службы графа. |
| `foundation_graph_circuit_get` | Read graph circuit-breaker state. | Читает состояние защиты графовой службы от отказов. |
| `foundation_graph_fact_put` | Write a scoped graph fact. | Записывает факт в заданной области графа. |
| `foundation_graph_search` | Search graph facts. | Ищет факты в графе. |
| `foundation_graph_tombstone` | Tombstone a graph fact. | Помечает факт графа как удалённый. |

## Memory / Память

| Tool | EN | RU |
|---|---|---|
| `foundation_memory_migrate` | Apply AgentMemory migrations. | Применяет миграции AgentMemory. |
| `foundation_memory_health` | Read AgentMemory health. | Читает состояние AgentMemory. |
| `foundation_memory_scope_set` | Set the default memory scope. | Устанавливает область памяти по умолчанию. |
| `foundation_memory_save` | Save scoped memory. | Сохраняет память в заданной области. |
| `foundation_memory_search` | Search scoped memories. | Ищет записи памяти в заданной области. |
| `foundation_memory_context` | Retrieve scoped context contribution. | Получает контекстное дополнение из заданной области памяти. |

## Beads, work, fragments / Задачи, работа, фрагменты

| Tool | EN | RU |
|---|---|---|
| `foundation_beads_migrate` | Apply Beads workspace migrations. | Применяет миграции пространства Beads. |
| `foundation_beads_health` | Read Beads health. | Читает состояние Beads. |
| `foundation_beads_create` | Create a tracked task. | Создаёт отслеживаемую задачу. |
| `foundation_beads_get` | Read a tracked task. | Читает отслеживаемую задачу. |
| `foundation_beads_claim` | Claim a task for a worker. | Закрепляет задачу за исполнителем. |
| `foundation_beads_close` | Close a tracked task. | Закрывает отслеживаемую задачу. |
| `foundation_work_reconcile` | Reconcile tracked work state. | Сверяет состояние отслеживаемой работы. |
| `foundation_fragment_record` | Record a source-fragment envelope; no evidence promotion. | Регистрирует оболочку исходного фрагмента; не повышает его до доказательства. |
| `foundation_fragment_promote` | Promote a validated recorded fragment. | Повышает проверенный зарегистрированный фрагмент. |
| `foundation_state_reconcile` | Assess cross-store work state; no write. | Оценивает согласованность состояния между хранилищами; не записывает. |

## Hooks / Обработчики событий

All five pass through a bounded Foundation hook queue; failure to persist is reported, not silently treated as research evidence. / Все пять проходят через ограниченную очередь Foundation; сбой записи не превращается в доказательство исследования.

| Hook | EN | RU |
|---|---|---|
| `on_session_start` | Record session start. | Записывает начало сеанса. |
| `pre_llm_call` | Record pre-call event; may return scoped memory context. | Записывает событие перед вызовом модели; может вернуть контекст из памяти. |
| `post_tool_call` | Record tool completion event. | Записывает событие после вызова инструмента. |
| `post_llm_call` | Record model-call completion event. | Записывает событие после вызова модели. |
| `on_session_end` | Record session end. | Записывает завершение сеанса. |
