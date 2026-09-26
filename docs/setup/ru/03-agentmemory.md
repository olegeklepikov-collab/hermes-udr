# 3. AgentMemory: нативная служба и подключение Hermes

Закреплены `@agentmemory/agentmemory@0.9.29`, исходный commit `2d38dafede67d0d4ed920cde94d2106e98825b8a` и движок iii **0.11.2**. На каждом компьютере служба, данные и учётная запись принадлежат его экземпляру; общая облачная память не включается.

## Установка

На macOS/Linux:
```bash
npm install --prefix "$UDR_SOFTWARE/agentmemory" '@agentmemory/agentmemory@0.9.29'
export AM_CLI="$UDR_SOFTWARE/agentmemory/node_modules/@agentmemory/agentmemory/dist/cli.mjs"
node "$AM_CLI" --help
mkdir -p "$UDR_STATE/agentmemory"
```
Windows PowerShell:
```powershell
npm.cmd install --prefix "$env:UDR_SOFTWARE\agentmemory" '@agentmemory/agentmemory@0.9.29'
$amCli = "$env:UDR_SOFTWARE\agentmemory\node_modules\@agentmemory\agentmemory\dist\cli.mjs"
node $amCli --help
New-Item -ItemType Directory -Force "$env:UDR_STATE\agentmemory" | Out-Null
```

Для iii скачайте соответствующий архив скриптом `scripts/get_asset.py`, который проверяет SHA-256 из `reference/native-tools.lock.json`:

| Система | Архив |
|---|---|
| macOS Apple Silicon | `iii-aarch64-apple-darwin.tar.gz` |
| macOS Intel | `iii-x86_64-apple-darwin.tar.gz` |
| Linux x64 | `iii-x86_64-unknown-linux-gnu.tar.gz` |
| Linux ARM64 | `iii-aarch64-unknown-linux-gnu.tar.gz` |
| Windows x64 | `iii-x86_64-pc-windows-msvc.zip` |

Пример Linux x64; для macOS замените имя архива из таблицы:
```bash
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/get_asset.py" iii-x86_64-unknown-linux-gnu.tar.gz "$UDR_SOFTWARE/downloads"
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/install_binary.py" "$UDR_SOFTWARE/downloads/iii-x86_64-unknown-linux-gnu.tar.gz" iii "$UDR_SOFTWARE/bin"
"$UDR_SOFTWARE/bin/iii" --version
```
Windows:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\get_asset.py" iii-x86_64-pc-windows-msvc.zip "$env:UDR_SOFTWARE\downloads"
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\install_binary.py" "$env:UDR_SOFTWARE\downloads\iii-x86_64-pc-windows-msvc.zip" iii.exe "$env:UDR_SOFTWARE\bin"
& "$env:UDR_SOFTWARE\bin\iii.exe" --version
```
Ожидается версия 0.11.2. Скрипт не перезаписывает существующий бинарник.

## Запуск служб

Скопируйте `config/iii-native.json.example` в `$UDR_STATE/agentmemory/iii-native.json`. Подставьте абсолютные пути `file_path`; на Windows используйте `C:/...`. Все три слушающих адреса — `127.0.0.1`: движок 49134, REST 3111, потоки 3112. При конфликте выберите свободные порты и согласованно измените конфигурацию, переменные Node и клиентов.

В первом терминале запустите движок:
```bash
"$UDR_SOFTWARE/bin/iii" --config "$UDR_STATE/agentmemory/iii-native.json" --no-update-check
```
Windows:
```powershell
& "$env:UDR_SOFTWARE\bin\iii.exe" --config "$env:UDR_STATE\agentmemory\iii-native.json" --no-update-check
```
Во втором терминале повторно задайте переменные раздела 01 и запустите обработчик:
```bash
export III_ENGINE_URL=ws://127.0.0.1:49134
export III_REST_PORT=3111
export III_STREAM_PORT=3112
export AGENT_ID=hermes-udr
export AGENTMEMORY_AGENT_SCOPE=isolated
export AGENTMEMORY_AUTO_COMPRESS=false
export SNAPSHOT_DIR="$UDR_STATE/agentmemory/snapshots"
node "$UDR_SOFTWARE/agentmemory/node_modules/@agentmemory/agentmemory/dist/index.mjs"
```
Windows:
```powershell
$env:III_ENGINE_URL = 'ws://127.0.0.1:49134'
$env:III_REST_PORT = '3111'
$env:III_STREAM_PORT = '3112'
$env:AGENT_ID = 'hermes-udr'
$env:AGENTMEMORY_AGENT_SCOPE = 'isolated'
$env:AGENTMEMORY_AUTO_COMPRESS = 'false'
$env:SNAPSHOT_DIR = "$env:UDR_STATE\agentmemory\snapshots"
node "$env:UDR_SOFTWARE\agentmemory\node_modules\@agentmemory\agentmemory\dist\index.mjs"
```
Эти команды запускают iii и Node напрямую, без автоматического контейнерного маршрута. AgentMemory 0.9.29 также читает параметры из `~/.agentmemory/.env`; если в той же учётной записи уже есть AgentMemory, проверьте совместимость настроек или используйте отдельную учётную запись ОС. `HERMES_HOME` не изолирует этот upstream-файл. Автоматическое сжатие моделью выключено; его включение требует настроенного поставщика и отдельного решения о передаче содержимого.

Проверьте `http://127.0.0.1:3111/agentmemory/health`: `curl -f` на macOS/Linux, `Invoke-RestMethod` в PowerShell. Ожидается `status: healthy`, версия `0.9.29`. Основные записи сохраняются файловым адаптером iii; очередь заданий в этой конфигурации находится в памяти. Перед остановкой дождитесь завершения активных операций; сначала остановите Node, затем iii.

## Подключение к Hermes

В версии 0.9.29 `agentmemory connect hermes` — заглушка, сообщающая о ручной настройке YAML. Не считайте её успешной установкой.

Добавьте в `mcp_servers` выбранного `$HERMES_HOME/config.yaml`, сохранив остальные ключи:
```yaml
mcp_servers:
  agentmemory:
    command: /ABSOLUTE/PATH/TO/node
    args: [/ABSOLUTE/UDR_SOFTWARE/agentmemory/node_modules/@agentmemory/agentmemory/dist/cli.mjs, mcp, --tools, core]
    env:
      AGENTMEMORY_URL: http://127.0.0.1:3111
    enabled: true
```
Для Windows `command` — абсолютный путь к `node.exe`; в YAML удобны прямые слеши `C:/...`. Явный вызов `node` исключает зависимость от обработки npm.cmd оболочкой. `hermes mcp list` и `hermes mcp test agentmemory` должны показывать подключение; после изменения начните новую сессию.

В самостоятельном режиме Research автоматический контекст можно подключить отдельным официальным плагином памяти. В управляемом режиме Foundation читает и синхронизирует память самостоятельно; второй автоматический обработчик для того же сеанса не включайте:
```sh
hermes plugins install rohitg00/agentmemory/integrations/hermes --ref 2d38dafede67d0d4ed920cde94d2106e98825b8a --no-enable
hermes plugins doctor agentmemory --ci
hermes plugins enable agentmemory
```
После просмотра плагина и успешной диагностики установите:
```yaml
memory:
  provider: agentmemory
```
И проверьте `hermes memory status`. При отказе сканера разберите отчёт; не отключайте проверку глобально. Плагин вызывает `register_memory_provider`, предзагрузку и синхронизацию сеанса. Его реализация сокращает отдельные поля синхронизируемого диалога; она не заменяет полный корпус Research. Автоматический захват переписки включайте осознанно. MCP-инструменты и callback поставщика памяти — разные механизмы; они не реализуют канонический приём Foundation.

## Проверка сохранения и остановка

Через `memory_save` сохраните только синтетическую запись `native-memory-probe-20260926`, затем получите её `memory_recall`/`memory_smart_search` по фактической схеме сервера. Штатно остановите только собственную службу, запустите с тем же data-dir и повторите поиск. Сравните проектную область. Не используйте `stop --force` для чужого процесса. Для автозапуска создайте две отдельные службы по разделу 08: iii с `--config`, затем Node с `dist/index.mjs` и переменными из этого раздела.

Источники: [точная инструкция 0.9.29](https://github.com/rohitg00/agentmemory/blob/v0.9.29/INSTALL_FOR_AGENTS.md), [CLI и Windows-ветвь](https://github.com/rohitg00/agentmemory/blob/v0.9.29/src/cli.ts), [плагин Hermes](https://github.com/rohitg00/agentmemory/tree/v0.9.29/integrations/hermes), [iii 0.11.2](https://github.com/iii-hq/iii/releases/tag/iii/v0.11.2).
