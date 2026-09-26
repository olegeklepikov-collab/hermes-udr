# SQLite: установка и работа с базами

SQLite — библиотека и файлы базы, а не отдельный сервер. Для неё не создаются порт, служба systemd или Windows Service. Устанавливаем CLI `sqlite3` для обслуживания и отдельно проверяем модуль `sqlite3` внутри Python Hermes. `pip install sqlite3` не нужен и не является правильной установкой стандартного модуля.

## macOS

```bash
brew install sqlite
export PATH="$(brew --prefix sqlite)/bin:$PATH"
sqlite3 --version
"$HERMES_PYTHON" -c 'import sqlite3; print(sqlite3.sqlite_version); print(sqlite3.connect(":memory:").execute("select sqlite_version()").fetchone()[0])'
```

Не заменяйте библиотеку SQLite, поставляемую macOS. Homebrew CLI и Python могут использовать разные версии; запишите обе. Проверка временного соединения выше завершится вместе с процессом Python.

## Linux (Ubuntu 24.04)

```bash
sudo apt-get update
sudo apt-get install -y sqlite3 libsqlite3-dev
sqlite3 --version
"$HERMES_PYTHON" -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

Если стандартный модуль отсутствует, переустановите Python из поддержанного дистрибутива или пересоберите его с библиотекой SQLite. Установка CLI сама по себе не исправляет интерпретатор, собранный без `_sqlite3`.

## Windows, нативная PowerShell

Нужен Python 3.13 из общего раздела. Официальный архив SQLite 3.53.4 на 26.09.2026: `sqlite-tools-win-x64-3530400.zip`; для Windows ARM64 — отдельный `sqlite-tools-win-arm64-3530400.zip`. Не смешивайте DLL разных архитектур.

```powershell
$sqliteDir = Join-Path $env:UDR_SOFTWARE 'sqlite-3.53.4'
New-Item -ItemType Directory -Force $sqliteDir | Out-Null
$archive = Join-Path $sqliteDir 'sqlite-tools.zip'
Invoke-WebRequest 'https://sqlite.org/2026/sqlite-tools-win-x64-3530400.zip' -OutFile $archive
# SQLite publishes SHA3-256, not ordinary SHA-256. Python verifies it:
& $env:HERMES_PYTHON -c 'import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); expected="88b4659fe747896b853af10157316b4ade143553efb89c1c8ca7423a278dcc8b"; actual=hashlib.sha3_256(p.read_bytes()).hexdigest(); sys.exit(0 if actual==expected else 1)' $archive
if ($LASTEXITCODE -ne 0) { throw 'SQLite SHA3-256 не совпал' }
Expand-Archive -LiteralPath $archive -DestinationPath $sqliteDir
$env:PATH = "$sqliteDir;$env:PATH"
& "$sqliteDir\sqlite3.exe" --version
& $env:HERMES_PYTHON -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

Для ARM64 замените URL на `https://sqlite.org/2026/sqlite-tools-win-arm64-3530400.zip`, ожидаемый SHA3-256 на `0c99da3702b2517c1d738207db7e945e5c55be7748141a192a1c8f3b4455c44b`. Путь сохраните в пользовательской конфигурации служб, не изменяя системные DLL. Повторное распаковывание делайте в новый каталог, не поверх работающей версии.

## Проверка без доступа к рабочим базам

В отдельном пустом каталоге выполните на любой ОС (в PowerShell `sqlite3` заменяется на полный путь к `sqlite3.exe`):

```sh
sqlite3 setup-check.sqlite "CREATE TABLE probe(id INTEGER PRIMARY KEY, value TEXT); INSERT INTO probe VALUES(1,'native-sqlite-ok'); PRAGMA integrity_check; SELECT * FROM probe;"
sqlite3 -readonly setup-check.sqlite "SELECT value FROM probe WHERE id=1;"
```

Ожидаются `ok` и `native-sqlite-ok`. Повтор команды создания таблицы в той же тестовой базе намеренно завершится ошибкой — выберите новый файл. Рабочие таблицы создаются миграциями соответствующего приложения, а не этой командой.

## Чьи базы обслуживаются

| Файл | Владелец |
|---|---|
| `$HERMES_HOME/state.db` | Диалоги Hermes |
| `research-runs/<run>/corpus.sqlite` | Источники, заметки, план и журнал Research |
| `$HERMES_FOUNDATION_ROOT/runtime/runtime.sqlite3` | Координатор Foundation, когда поддержанный вариант Foundation включён |
| `runtime/profile-transport.sqlite3` и базы наблюдаемости | Соответствующие службы Foundation |

Обобщённое имя `runtime_ops.db` из старой спецификации не является фактическим именем файла текущей беты. SQLite не заменяет Dolt/Beads. Не создавайте общую базу для всех компонентов и не подключайте к ней несколько самодельных писателей.

## Резервное копирование и восстановление

Используйте включённый `scripts/sqlite_backup.py`, который применяет штатный Backup API и читает источник в режиме read-only. Это сохраняет согласованный снимок при наличии WAL; простого копирования одного открытого `.sqlite` недостаточно.

macOS/Linux:
```bash
"$HERMES_PYTHON" "$UDR_SETUP_DIR/scripts/sqlite_backup.py" /absolute/source.sqlite /absolute/backups/copy-20260926.sqlite
sqlite3 -readonly /absolute/backups/copy-20260926.sqlite 'PRAGMA integrity_check;'
```
Windows:
```powershell
& $env:HERMES_PYTHON "$env:UDR_SETUP_DIR\scripts\sqlite_backup.py" 'C:\absolute\source.sqlite' 'C:\absolute\backups\copy-20260926.sqlite'
& "$sqliteDir\sqlite3.exe" -readonly 'C:\absolute\backups\copy-20260926.sqlite' 'PRAGMA integrity_check;'
```

Для проверки восстановления копируйте резервную копию в ещё один новый каталог, откройте её read-only и проверьте ожидаемую запись через приложение. Перед производственным восстановлением остановите владельца базы и сохраните текущую базу вместе с WAL/SHM как отдельный снимок. Не копируйте старые WAL/SHM поверх восстановленной согласованной базы. Переключение выполняется владельцем приложения, не командой из этого диагностического примера.

Источники: [официальные архивы и SHA3](https://sqlite.org/download.html), [CLI](https://sqlite.org/cli.html), [Backup API Python](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup), [SQLite WAL](https://sqlite.org/wal.html).
