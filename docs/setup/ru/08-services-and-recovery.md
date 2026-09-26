# 8. Автозапуск и восстановление

Сначала проверьте каждый процесс в foreground. MCP по stdio (Serena, Zvec MCP, AgentMemory shim) запускает сам Hermes — отдельная фоновая служба им не нужна. Долгоживущими являются iii и обработчик AgentMemory, Neo4j, Graphiti HTTP, Phoenix, Collector и при необходимости Dolt SQL.

## 8.1. Один формат параметров

Создайте приватный JSON для каждой службы. Пример AgentMemory (подставляются **реальные абсолютные пути**, а не буквальные `/ABSOLUTE`):
```json
{
  "name": "agentmemory",
  "argv": ["/ABSOLUTE/node", "/ABSOLUTE/software/agentmemory/node_modules/@agentmemory/agentmemory/dist/index.mjs"],
  "cwd": "/ABSOLUTE/state/agentmemory",
  "env": {"III_ENGINE_URL": "ws://127.0.0.1:49134", "III_REST_PORT": "3111", "III_STREAM_PORT": "3112", "AGENT_ID": "hermes-udr", "AGENTMEMORY_AGENT_SCOPE": "isolated", "AGENTMEMORY_AUTO_COMPRESS": "false", "SNAPSHOT_DIR": "/ABSOLUTE/state/agentmemory/snapshots"}
}
```
Windows использует `C:/.../node.exe`. В `argv` не записываются ключи и пароли. Graphiti может указать `env_file` с абсолютным путём к приватному `.env`; запускающий Python должен иметь `python-dotenv` (он входит в закреплённый Hermes). `service_exec.py` не печатает значения среды.

Для iii создайте отдельную службу с `argv=[ABSOLUTE_III, --config, ABSOLUTE_III_CONFIG, --no-update-check]`; запустите её перед обработчиком AgentMemory.

Другие команды:

| Служба | Команда |
|---|---|
| Neo4j macOS/Linux | `NEO4J_HOME/bin/neo4j console` |
| Neo4j Windows | Предпочтительна собственная команда `neo4j.bat windows-service install`, затем `start` из административного терминала; не регистрируйте повторно уже существующую службу |
| Graphiti | Python его venv, затем абсолютный `mcp_server/main.py`, `--config`, путь к YAML, `--database-provider neo4j`, `--transport http`; cwd — `mcp_server` |
| Phoenix | `phoenix serve`; `PHOENIX_HOST=127.0.0.1`, `PHOENIX_PORT=6006`, `PHOENIX_WORKING_DIR` — выделенный каталог |
| Collector | `otelcol-contrib --config=ABSOLUTE/collector.yaml` |
| Dolt SQL | `dolt sql-server --config ABSOLUTE/server.yaml`, только после настройки полномочий |

## 8.2. Генерация и регистрация

Скрипт **только создаёт файлы**, не регистрирует и не запускает службы. Запускайте его Python Hermes:
```bash
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/render_services.py" /ABSOLUTE/agentmemory.json /ABSOLUTE/generated --platform linux
```
Для macOS замените `linux` на `macos`. PowerShell:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\render_services.py" 'C:\ABSOLUTE\agentmemory.json' 'C:\ABSOLUTE\generated' --platform windows
```
Секреты находятся в приватном env-файле, а не в plist/unit/JSON. Установите права на каталоги, журналы и env: macOS/Linux 0700 на каталог и 0600 на файл; Windows — ACL текущего владельца, SYSTEM и при необходимости локальных администраторов. Путь из `env_file` передаётся программе, а не содержимое файла.

Linux, пользовательская служба:
```bash
mkdir -p "$HOME/.config/systemd/user"
cp -f /ABSOLUTE/generated/agentmemory.service "$HOME/.config/systemd/user/agentmemory.service"
systemctl --user daemon-reload
systemctl --user enable --now agentmemory.service
systemctl --user status agentmemory.service
journalctl --user -u agentmemory.service -n 30
```
Если требуется работа после выхода, администратор выполняет `sudo loginctl enable-linger USERNAME`. Остановка — `systemctl --user stop agentmemory.service`; не используйте её для чужой службы с таким именем.

macOS, LaunchAgent:
```bash
plutil -lint /ABSOLUTE/generated/org.hermesudr.agentmemory.plist
launchctl bootstrap "gui/$(id -u)" /ABSOLUTE/generated/org.hermesudr.agentmemory.plist
launchctl print "gui/$(id -u)/org.hermesudr.agentmemory"
```
Удаление регистрации — `launchctl bootout "gui/$(id -u)" /ABSOLUTE/generated/org.hermesudr.agentmemory.plist`. Это запуск в пользовательской сессии, не обещание работы до входа пользователя. Журналы пишутся рядом с generated-файлом; ограничьте к ним доступ и настройте ротацию по своей политике.

Windows, Task Scheduler:
```powershell
& 'C:\ABSOLUTE\generated\agentmemory-register.ps1'
Start-ScheduledTask -TaskName 'HermesUDR-agentmemory'
Get-ScheduledTaskInfo -TaskName 'HermesUDR-agentmemory'
```
Задача создаётся для входа текущего пользователя и не требует передачи его пароля скрипту. Это не Windows Service и не круглосуточный запуск до входа. При удалении сначала штатно остановите приложение, затем `Unregister-ScheduledTask -TaskName 'HermesUDR-agentmemory' -Confirm:$false`. Остановка родительского задания не гарантирует завершения всех собственных дочерних демонов приложения — используйте его штатный `stop` и проверяйте порты.

## 8.3. Hermes gateway и Telegram

После настройки модели выполните `hermes gateway setup`; токен и разрешённые пользователи задаются владельцем локально. Запуск в foreground: `hermes gateway run`. Для автозапуска используйте штатный `hermes gateway install --help`, затем поддержанный текущей ОС вариант установщика. Не создавайте второй gateway поверх уже работающего. Настройте allowlist, проведите один собственный тестовый диалог и отдельную проверку отказа для постороннего отправителя. Отправка сообщений не выполняется самим пакетом инструкций.

Патч Telegram из подписанной поставки относится к закреплённому commit Hermes. Перед его применением в новой копии сверьте исходный SHA из `bridge-lock.json`, выполните `git apply --check`, затем применение и сверку итогового SHA. Не используйте имя патча как доказательство, что исправление уже установлено. Bot Mode отдельно не инициируется.

## 8.4. Резервирование

- SQLite: включённый Backup API, проверка integrity и восстановление в новый файл.
- AgentMemory: штатно остановленный daemon и его iii, копия выбранного data-dir **и** настроек/версии; восстановление в новый каталог с теми же правами, затем реальный поиск синтетической записи.
- Neo4j Community: штатный остановленный dump/load, не сырая копия работающего каталога.
- Zvec: закрыть коллекции, сохранить источники/параметры индекса и каталог либо перестроить в новом каталоге; проверить документ, а не только наличие файлов.
- Dolt/Beads: история, конфигурация, права и данные; JSONL не заменяет копию.
- Phoenix: остановленный рабочий каталог по разделу 07.
- Hermes/Research: конфигурация с отдельной защитой секретов, диалоги, полный corpus и исходные файлы; модели и подключённые сервисы фиксируются отдельно.

Восстановление никогда не начинается с удаления рабочего корня. Сначала новый каталог, проверка чтения и сравнение ожидаемых объектов; переключение допускает владелец экземпляра. Общая надпись «backup passed» не подтверждает восстановление каждой службы.
