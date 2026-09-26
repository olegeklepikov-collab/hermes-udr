# 9. Dolt и Beads нативно

Используются Dolt **2.2.1** и Beads **1.1.0**, как в опубликованной паре. Beads уже использует собственный встроенный Dolt; ему не требуется общий SQL-сервер предметных баз. Не переносите его автоматически в server mode ради соответствия старому тексту. JSONL — экспорт, не основная база.

## Доставка исполняемых файлов

`reference/native-tools.lock.json` содержит официальные URL и SHA-256 для Linux/macOS x64/arm64 и Windows. Пример Linux x64:
```bash
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/get_asset.py" dolt-linux-amd64.tar.gz "$UDR_SOFTWARE/downloads"
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/install_binary.py" "$UDR_SOFTWARE/downloads/dolt-linux-amd64.tar.gz" dolt "$UDR_SOFTWARE/bin"
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/get_asset.py" beads_1.1.0_linux_amd64.tar.gz "$UDR_SOFTWARE/downloads"
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/install_binary.py" "$UDR_SOFTWARE/downloads/beads_1.1.0_linux_amd64.tar.gz" bd "$UDR_SOFTWARE/bin"
export PATH="$UDR_SOFTWARE/bin:$PATH"
dolt version
bd --version
```
На macOS замените `linux` на `darwin`; для arm64 замените `amd64` на `arm64`. Скрипт установки выбирает единственный исполняемый файл из архива и не заменяет отличающийся существующий файл.

Windows x64:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\get_asset.py" dolt-windows-amd64.zip "$env:UDR_SOFTWARE\downloads"
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\install_binary.py" "$env:UDR_SOFTWARE\downloads\dolt-windows-amd64.zip" dolt.exe "$env:UDR_SOFTWARE\bin"
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\get_asset.py" beads_1.1.0_windows_amd64.zip "$env:UDR_SOFTWARE\downloads"
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\install_binary.py" "$env:UDR_SOFTWARE\downloads\beads_1.1.0_windows_amd64.zip" bd.exe "$env:UDR_SOFTWARE\bin"
$env:PATH = "$env:UDR_SOFTWARE\bin;$env:PATH"
dolt version
bd --version
```

Ожидаемые версии — 2.2.1 и 1.1.0. Windows ARM64 имеет Beads-архив, но отсутствие Dolt ARM64 в lock нельзя скрывать установкой x64 как якобы нативной ARM64 сборки.

## Изолированный Beads

Создайте **новый** каталог `$UDR_STATE/beads-workspace` и отдельный Git-корень. Это предотвращает обнаружение родительской базы проекта.

macOS/Linux:
```bash
mkdir -p "$UDR_STATE/beads-workspace"
git -C "$UDR_STATE/beads-workspace" init
export BEADS_DIR="$UDR_STATE/beads-workspace/.beads"
cd "$UDR_STATE/beads-workspace"
bd init --prefix KWF --non-interactive --skip-agents --skip-hooks --sandbox
bd status
```
Windows:
```powershell
New-Item -ItemType Directory -Force "$env:UDR_STATE\beads-workspace" | Out-Null
git -C "$env:UDR_STATE\beads-workspace" init
$env:BEADS_DIR = "$env:UDR_STATE\beads-workspace\.beads"
Set-Location "$env:UDR_STATE\beads-workspace"
bd init --prefix KWF --non-interactive --skip-agents --skip-hooks --sandbox
bd status
```
Для проверки создайте синтетическую задачу: `bd create "Native setup probe" --type task --priority 2`; используйте возвращённый ID в `bd show ID`, `bd update ID --claim`, `bd close ID`. Не подставляйте ID из чужого экземпляра. Уберите временный `BEADS_DIR` из других терминалов, чтобы команды случайно не выполнялись в тестовой базе. В Foundation рабочая область ожидается в другом точном корне `$HERMES_FOUNDATION_ROOT/beads-workspace`; эта нативная самостоятельная область не выдаётся за автоматически подключённую к Foundation.

## Предметные базы Dolt

Для нативной самостоятельной проверки создайте новый каталог `$UDR_STATE/dolt/kw_core`. Выполните в нём:
```sh
dolt init --name 'Hermes UDR local owner' --email 'local@localhost.invalid'
dolt sql -q "CREATE TABLE setup_probe (id INT PRIMARY KEY, value TEXT); INSERT INTO setup_probe VALUES (1,'native-dolt-ok');"
dolt add setup_probe
dolt commit --author 'Hermes UDR local owner <local@localhost.invalid>' -m 'Native setup probe'
dolt sql -q "SELECT * FROM setup_probe;"
dolt log -n 1
```
Включение SQL-сервера необязательно для CLI-работы. Если он нужен, используйте единый loopback-порт **3317**, не 3307, и `config/dolt-server.yaml.example` с абсолютными путями. Запуск: `dolt sql-server --config /ABSOLUTE/config/dolt-server.yaml`. Под Windows та же команда использует `dolt.exe`, пути YAML записываются прямыми слешами.

Для управляемого Foundation используйте его `scripts/provision_dolt_sql.py`: он создаёт именованных `foundation_writer`/`foundation_admin`, права четырёх баз и ограничение ветвей. Порядок: при остановленном SQL-сервере выполнить `DoltStateAdapter(root).migrate(apply=True)` → просмотреть план `provision_dolt_sql.py --foundation-root ROOT --admin-secret-dir AUTHORITY` → повторить с `--apply` → запустить `dolt sql-server --config ROOT/dolt/server.yaml`. Подробные команды находятся в `DOLT_SQL.md` подписанного Foundation.

`AUTHORITY` — отдельный приватный каталог вне `ROOT`. Пароли создаются программой и передаются через стандартный ввод. На POSIX защищаются права владельца, на Windows — ACL. CLI-писатель не должен работать одновременно с SQL-писателем. Пустой сервер с безпарольным root не является готовой службой Foundation.

## Копия и восстановление

Для начального сценария остановите писателей и SQL-сервер, сохраните все каталоги `.dolt` вместе с конфигурацией, правами и журналом коммитов в отдельный резервный каталог. Восстановите в новый корень, выполните `dolt status`, `dolt log -n 1` и SQL-чтение контрольной строки. Для Beads дополнительно выполните `bd status` и чтение сохранённого ID при явно заданном `BEADS_DIR`. Копирование только JSONL или только таблиц без истории/прав не является полным восстановлением.

Источники: [Beads 1.1.0](https://github.com/gastownhall/beads/releases/tag/v1.1.0), [Dolt 2.2.1](https://github.com/dolthub/dolt/releases/tag/v2.2.1), [Dolt SQL Server](https://docs.dolthub.com/sql-reference/server/configuration), [фактическая схема Foundation](https://github.com/olegeklepikov-collab/hermes-udr/blob/v0.44.0-beta.2/components/foundation/DOLT_SQL.md).
