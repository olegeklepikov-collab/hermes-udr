# 10. Установка подписанных пакетов и проверка

Устанавливайте согласованную пару Research и Foundation из тега, указанного в `reference/native-tools.lock.json`. Подписи подтверждают точные байты поставки; проверка выбранного профиля и подключений выполняется на целевом экземпляре.

## Проверка подписи

На macOS/Linux Minisign установлен в разделе 01. Windows x64:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\get_asset.py" minisign-0.12-win64.zip "$env:UDR_SOFTWARE\downloads"
Expand-Archive "$env:UDR_SOFTWARE\downloads\minisign-0.12-win64.zip" "$env:UDR_SOFTWARE\minisign"
$minisign = "$env:UDR_SOFTWARE\minisign\minisign-win64\x86_64\minisign.exe"
& $minisign -v
```
Исходное доверие к открытому ключу устанавливает владелец. Его SHA-256 закреплён в реестре; ключ нельзя заменять только потому, что новый архив содержит другой.

macOS/Linux:
```bash
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/prepare_research_source.py" "$UDR_SOFTWARE/research-release" --component research
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/prepare_research_source.py" "$UDR_SOFTWARE/foundation-release" --component foundation
```
Windows:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\prepare_research_source.py" "$env:UDR_SOFTWARE\research-release" --component research --minisign $minisign
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\prepare_research_source.py" "$env:UDR_SOFTWARE\foundation-release" --component foundation --minisign $minisign
```
Скрипт сверяет SHA-256, Minisign и содержимое манифеста, затем создаёт локальный Git-источник без преобразования переводов строк. Для каждого результата используйте его `source_uri` и `local_install_commit`:
```sh
hermes plugins install SOURCE_URI --ref LOCAL_INSTALL_COMMIT --no-enable
```
Сначала установите Research, затем Foundation. Если сканер Hermes останавливает пользовательский источник, изучите фактический отчёт: `--force` допустим только для проверенных точных байтов и рассмотренного предупреждения, не при ошибке подписи.

Установите зависимости Foundation в выделенную среду Hermes:
```bash
"$HERMES_PYTHON" -m pip install 'zvec==0.7.0' 'PyMySQL==1.1.2' 'psutil==7.2.2'
```
В PowerShell используйте `& $env:HERMES_PYTHON -m pip install zvec==0.7.0 PyMySQL==1.1.2 psutil==7.2.2`. Если uv создал среду без pip, примените `uv pip install --python` с тем же путём Python.

## Нативное подключение Foundation

Службы AgentMemory и Neo4j должны отвечать по разделам 03 и 04. Создайте отдельную среду для обработчика Graphiti; MCP Graphiti использует свою среду:
```bash
uv venv --python 3.13 "$UDR_SOFTWARE/foundation-graph"
uv pip install --python "$UDR_SOFTWARE/foundation-graph/bin/python" 'graphiti-core==0.30.2' 'httpx==0.28.1'
export FOUNDATION_PLUGIN="$HERMES_HOME/plugins/hermes-foundation-bridge"
"$HERMES_PYTHON" "$FOUNDATION_PLUGIN/scripts/configure_native_runtime.py" --foundation-root "$HERMES_FOUNDATION_ROOT" --node "$(command -v node)" --graph-python "$UDR_SOFTWARE/foundation-graph/bin/python" --neo4j-password-file "$UDR_STATE/authority/neo4j.password"
```
Windows:
```powershell
uv venv --python 3.13 "$env:UDR_SOFTWARE\foundation-graph"
uv pip install --python "$env:UDR_SOFTWARE\foundation-graph\Scripts\python.exe" graphiti-core==0.30.2 httpx==0.28.1
$foundationPlugin = "$env:HERMES_HOME\plugins\hermes-foundation-bridge"
& $env:HERMES_PYTHON "$foundationPlugin\scripts\configure_native_runtime.py" --foundation-root $env:HERMES_FOUNDATION_ROOT --node (Get-Command node.exe).Source --graph-python "$env:UDR_SOFTWARE\foundation-graph\Scripts\python.exe" --neo4j-password-file "$env:UDR_STATE\authority\neo4j.password"
```
Скрипт запрашивает установленный пароль Neo4j без отображения и защищает файл. Он не меняет пароль базы. При нестандартных портах укажите `--agentmemory-url http://127.0.0.1:PORT` и `--neo4j-uri bolt://127.0.0.1:PORT`. Существующий `native-runtime.json` не перезаписывается. Для штатной работы службы запускаются раньше Hermes.

Проверьте регистрацию и включите плагины:
```sh
hermes plugins doctor ultra-deep-research --ci
hermes plugins doctor hermes-foundation-bridge --ci
hermes plugins enable ultra-deep-research --no-allow-tool-override
hermes plugins enable hermes-foundation-bridge --no-allow-tool-override
```
Research регистрирует 9 инструментов и 1 обработчик; Foundation — 64 и 5. Затем в новой сессии вызовите `foundation_bridge_migrate` с `apply=false`, просмотрите план и повторите с `apply=true` в выделенном корне. Параметры инструмента берутся из фактической схемы Hermes. Для SQL-режима выполните раздел 09 и `DOLT_SQL.md`; `foundation_bridge_health` должен подтвердить каждый включённый компонент.

## Выбор маршрута исследования

Самостоятельный режим:
```yaml
research:
  integration_mode: standalone
```
Он использует доступные инструменты Hermes/MCP. Проверочная команда macOS/Linux:
```bash
"$HERMES_PYTHON" "$HERMES_HOME/plugins/ultra-deep-research/skills/research/scripts/run_research.py" --question "Синтетические значения 20 и 30: рассчитайте изменение и укажите пределы вывода" --mode search
```
Windows:
```powershell
& $env:HERMES_PYTHON "$env:HERMES_HOME\plugins\ultra-deep-research\skills\research\scripts\run_research.py" --question 'Синтетические значения 20 и 30: рассчитайте изменение и укажите пределы вывода' --mode search
```
Управляемый режим требует `integration_mode: foundation` и вызова существующим узлом Hermes API `ResearchSession` → `run_in_host` → `complete`. Узел передаёт действующую задачу Beads, владельца, аренду и контракт; модель не создаёт себе разрешение текстовым утверждением. Подробный интерфейс — в `components/foundation/README.md` репозитория. Одно изменение YAML не заменяет интеграцию вызывающего узла.

## Приёмка экземпляра

Проверьте один синтетический проход: источник, заметка, отчёт, повторное чтение `corpus.sqlite`; ожидаемые изменения +10 и +50%. В управляемом режиме должны также появиться канонический черновик Dolt, подтверждённые записи памяти и графа. Повтор завершения не создаёт дубли; черновой вывод не получает научное одобрение автоматически.

Проверьте сохранение после штатного перезапуска и восстановление в отдельный каталог по разделу 08. Результаты автоматических проверок выпуска находятся в GitHub Actions. Они не заменяют проверку пользовательских ключей, модели, MCP-серверов и прикладного качества широкого исследования. Специализированные внешние сценарии Academic включаются только после проверки их зависимостей на целевой ОС; отсутствие требуемого источника или инструмента должно сохраняться как конкретное ограничение результата.
