# 4. Graphiti + Neo4j нативно

Этот путь использует официальный Graphiti MCP и Neo4j Community 5.26.31; он не требует FalkorDB или контейнеров. Graphiti 0.30.2 официально поддерживает Neo4j ≥5.26. Foundation использует типизированные операции над узлами `FoundationFact` через драйвер Graphiti/Neo4j. MCP Graphiti предоставляет отдельный эпизодический граф с извлечением сущностей и связей: эти два механизма имеют разные схемы и назначение.

## Neo4j и Java

Java 21: Ubuntu — `sudo apt-get install -y openjdk-21-jdk`; macOS — `brew install openjdk@21`, затем `export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"`; Windows — `winget install --exact --id EclipseAdoptium.Temurin.21.JDK`. После нового входа проверьте `java -version`; выберите именно JDK 21 для этой установки.

Скачайте закреплённой контрольной суммой из lock официальный архив, не плавающий latest:

macOS/Linux:
```bash
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/get_asset.py" neo4j-community-5.26.31-unix.tar.gz "$UDR_SOFTWARE/downloads"
tar -xzf "$UDR_SOFTWARE/downloads/neo4j-community-5.26.31-unix.tar.gz" -C "$UDR_SOFTWARE"
export NEO4J_HOME="$UDR_SOFTWARE/neo4j-community-5.26.31"
"$NEO4J_HOME/bin/neo4j" --version
mkdir -p "$UDR_STATE/neo4j/data" "$UDR_STATE/neo4j/logs" "$UDR_STATE/neo4j/run"
```
Windows:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\get_asset.py" neo4j-community-5.26.31-windows.zip "$env:UDR_SOFTWARE\downloads"
Expand-Archive "$env:UDR_SOFTWARE\downloads\neo4j-community-5.26.31-windows.zip" "$env:UDR_SOFTWARE"
$env:NEO4J_HOME = "$env:UDR_SOFTWARE\neo4j-community-5.26.31"
& "$env:NEO4J_HOME\bin\neo4j.bat" --version
New-Item -ItemType Directory -Force "$env:UDR_STATE\neo4j\data","$env:UDR_STATE\neo4j\logs","$env:UDR_STATE\neo4j\run" | Out-Null
```

В новой установке сохраните исходный `conf/neo4j.conf`, затем перенесите значения `config/neo4j.conf.example`, подставив абсолютные пути. Не оставляйте `/ABSOLUTE`. Проверка: `neo4j-admin server validate-config` (Windows — `bin/neo4j-admin.bat server validate-config`). Запуск в отдельном окне: `bin/neo4j console` либо `bin/neo4j.bat console`.

Откройте `http://127.0.0.1:7474`. При первом входе используйте первоначальную учётную запись Neo4j и немедленно задайте новый пароль через локальный интерфейс. Не помещайте новый пароль в командную строку. Проверьте `RETURN 1 AS ok;` в Browser; ожидается `1`. База данных по умолчанию называется `neo4j`. Порты 7474/7687 должны слушать loopback. Остановка foreground — Ctrl+C; остановка установленной службы — её штатная команда.

## Graphiti

macOS/Linux:
```bash
git clone --filter=blob:none https://github.com/getzep/graphiti.git "$UDR_SOFTWARE/graphiti"
git -C "$UDR_SOFTWARE/graphiti" checkout --detach eaa4128681bc53487138a4bbc22d58336ebe70d2
cd "$UDR_SOFTWARE/graphiti/mcp_server"
uv sync --frozen --python 3.13
```
Windows:
```powershell
git clone --filter=blob:none https://github.com/getzep/graphiti.git "$env:UDR_SOFTWARE\graphiti"
git -C "$env:UDR_SOFTWARE\graphiti" checkout --detach eaa4128681bc53487138a4bbc22d58336ebe70d2
Set-Location "$env:UDR_SOFTWARE\graphiti\mcp_server"
uv sync --frozen --python 3.13
```

Скопируйте `config/graphiti.yaml.example` в выделенный каталог `$UDR_STATE/graphiti/config.yaml`. Создайте локальный файл `.env` рядом с `main.py` в `graphiti/mcp_server` (не добавлять в Git). Он должен содержать значения:

```dotenv
NEO4J_PASSWORD=YOUR_LOCAL_PASSWORD
GRAPHITI_GROUP_ID=YOUR_PROJECT_NAMESPACE
GRAPHITI_LLM_MODEL=YOUR_RESOLVED_MODEL_ID
GRAPHITI_API_KEY=YOUR_PROVIDER_KEY
GRAPHITI_BASE_URL=YOUR_OPENAI_COMPATIBLE_API_BASE
GRAPHITI_EMBEDDER_MODEL=YOUR_EMBEDDING_MODEL_ID
GRAPHITI_EMBEDDER_API_KEY=YOUR_EMBEDDING_KEY
GRAPHITI_EMBEDDER_BASE_URL=YOUR_EMBEDDING_API_BASE
SEMAPHORE_LIMIT=2
```

Это перечень настраиваемых значений, не рабочие ключи. Выберите поддержанный поставщик; пример `openai` означает конфигурацию OpenAI-совместимого протокола. Для Anthropic/Gemini/Azure измените соответствующий раздел по закреплённому upstream config. Класс модели разрешается оператором в конкретный model ID до запуска Graphiti. OAuth Codex для Hermes не является автоматически ключом Graphiti или сервиса эмбеддингов. `dimensions` должен точно соответствовать выбранной модели; 1536 в примере не универсально. При смене размерности нужен новый индекс/пространство, а не запись несовместимых векторов поверх прежнего.

macOS/Linux: `chmod 0600 .env`. Windows: ограничьте ACL файла текущей учётной записью и администраторами через свойства безопасности либо `icacls`; не считайте Unix chmod проверкой NTFS-полномочий.

Запуск из каталога `mcp_server`:
```bash
uv run --frozen main.py --config "$UDR_STATE/graphiti/config.yaml" --database-provider neo4j --transport http
```
В PowerShell последний путь: `"$env:UDR_STATE\graphiti\config.yaml"`. Не используйте `--destroy-graph`. Если ключи не подхватились из `.env`, задайте их в среде своего процесса или используйте `service_exec.py` с `env_file`; не выводите значения в журнал.

Добавьте в конфигурацию Hermes:
```yaml
mcp_servers:
  graphiti:
    url: http://127.0.0.1:8000/mcp/
    enabled: true
    tools:
      include: [search_facts, search_nodes, get_episodes]
```

`hermes mcp test graphiti` должен получить фактическую схему. Обычный читатель не получает `clear_graph` и удаления. Для первичного синтетического теста в отдельном проектном пространстве временно разрешите `add_episode`, добавьте один эпизод, дождитесь обработки и найдите его через `search_facts`; затем верните список читателя. Перезапустите MCP и Neo4j и проверьте поиск повторно. Успешная постановка эпизода в очередь — ещё не подтверждение его индексации.

MCP вызывается по потребности исследования. Обязательное чтение и синхронизация Foundation выполняются его собственным адаптером, настроенным в разделе 10. Neo4j хранит данные в собственном каталоге, а не в SQLite/Dolt. Для Community резервная копия выполняется при остановленной базе штатной `neo4j-admin database dump neo4j --to-path=ABSOLUTE_BACKUP_DIR`; восстановление — `database load neo4j --from-path=...` в новую отдельную установку, без `--overwrite-destination` поверх работающей базы.

Источники: [Graphiti 0.30.2 MCP](https://github.com/getzep/graphiti/blob/v0.30.2/mcp_server/README.md), [его конфигурация](https://github.com/getzep/graphiti/blob/v0.30.2/mcp_server/config/config.yaml), [Neo4j 5.26.31](https://neo4j.com/deployment-center/), [Windows](https://neo4j.com/docs/operations-manual/current/installation/windows/), [Java и ОС](https://neo4j.com/docs/operations-manual/current/installation/requirements/).
