# Mirage 0.0.6: локальное чтение файлов из Hermes

Эта инструкция использует выпуск `mirage-ai==0.0.6` и совместимый пакет `mcp==1.30.0`. Требуется Python 3.12; его устанавливает `uv`, подготовленный в [разделе 01](01-platform-and-hermes.md). Mirage запускается непосредственно в macOS, Linux или Windows; контейнеры, подсистема Linux в Windows и монтирование через FUSE не нужны. Программные файлы находятся в `UDR_SOFTWARE/mirage`, данные — в `UDR_STATE/mirage/data`. Пример открывает только этот каталог и не требует учётных данных.

## Установка на macOS и Linux

В терминале выполните:

```sh
mkdir -p "$UDR_SOFTWARE/mirage" "$UDR_STATE/mirage/data"
cd "$UDR_SOFTWARE/mirage"
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python 'mirage-ai==0.0.6' 'mcp==1.30.0'
printf 'Пример для чтения\n' > "$UDR_STATE/mirage/data/example.txt"
.venv/bin/mirage --help
```

Python 3.12 управляется `uv` и не заменяет интерпретатор Hermes.

Создайте `workspace.yaml` в каталоге `$UDR_SOFTWARE/mirage`:

```sh
cat > workspace.yaml <<YAML
mode: READ
runtimes:
  - vfs
mounts:
  /data:
    resource: disk
    mode: READ
    config:
      root: "$UDR_STATE/mirage/data"
YAML
```

## Установка на Windows

В PowerShell выполните:

```powershell
$mirageDir = Join-Path $env:UDR_SOFTWARE 'mirage'
$dataDir = Join-Path $env:UDR_STATE 'mirage\data'
New-Item -ItemType Directory -Force $mirageDir,$dataDir | Out-Null
Set-Location $mirageDir
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .\.venv\Scripts\python.exe 'mirage-ai==0.0.6' 'mcp==1.30.0'
'Пример для чтения' | Set-Content -Encoding utf8 (Join-Path $dataDir 'example.txt')
& .\.venv\Scripts\mirage.exe --help
```

Создайте `workspace.yaml` в `$env:UDR_SOFTWARE\mirage`:

```powershell
$dataPath = (Resolve-Path $dataDir).Path.Replace('\', '/').Replace("'", "''")
@"
mode: READ
runtimes:
  - vfs
mounts:
  /data:
    resource: disk
    mode: READ
    config:
      root: '$dataPath'
"@ | Set-Content -Encoding utf8 .\workspace.yaml
```

`/data` — имя каталога внутри Mirage; `root` указывает на `$env:UDR_STATE\mirage\data`. Для Windows используйте Python и Hermes, запущенные в одной среде Windows.

## Подключение к Hermes

Добавьте следующий раздел в `$HERMES_HOME/config.yaml` выбранного профиля Hermes (`$env:HERMES_HOME\config.yaml` в PowerShell). Если `mcp_servers` уже есть, добавьте только запись `mirage_local`, сохранив остальные подключения. Подставьте **полные пути** к `mirage` и `workspace.yaml` из `$UDR_SOFTWARE/mirage`:

```yaml
mcp_servers:
  mirage_local:
    command: "/ABSOLUTE/UDR_SOFTWARE/mirage/.venv/bin/mirage"
    args: ["mcp", "/ABSOLUTE/UDR_SOFTWARE/mirage/workspace.yaml"]
    enabled: true
    tools:
      include: ["read", "ls", "grep"]
```

На Windows замените `command` на путь вида `C:/Users/ИМЯ/AppData/Local/HermesUDR/software/mirage/.venv/Scripts/mirage.exe`, а путь в `args` — на `C:/Users/ИМЯ/AppData/Local/HermesUDR/software/mirage/workspace.yaml`. Подставьте фактическое значение `UDR_SOFTWARE`. Прямые косые черты в этих путях избавляют от экранирования обратных косых черт в YAML.

Проверьте подключение командой `hermes mcp test mirage_local`, затем запустите `hermes chat` или выполните `/reload-mcp` в действующем сеансе. Попросите Hermes показать содержимое `/data/example.txt` через инструмент Mirage `read` и перечислить `/data` через `ls`. В Ultra Deep Research доступность обнаруженных инструментов можно дополнительно проверить вызовом `research_workspace(action="capabilities")`; наличие в перечне само по себе не подтверждает успешное чтение файла.

## Границы доступа и совместимости

- `mode: READ` задан и для пространства, и для его единственного каталога. `runtimes: [vfs]` оставляет внутренние команды Mirage и исключает выполнение программ компьютера через его среды исполнения. Hermes получает только три инструмента чтения: `read`, `ls`, `grep`. Сервер Mirage также умеет объявлять `execute_command`, `write`, `edit`, но фильтр Hermes их скрывает; попытка записи в это пространство отклоняется режимом `READ`.
- Mirage не изолирует весь компьютер: процессу сервера всё равно доступны полномочия пользователя ОС. Размещайте в `data` только файлы, которые можно передавать выбранной модели Hermes. Не добавляйте другие каталоги, сетевые ресурсы или программы в эту конфигурацию без отдельной оценки доступа.
- Выпуск 0.0.6 требует пакет `mcp` поколения 1.x: без закрепления версии установщик может выбрать `mcp` 2.x, с которым запуск сервера Mirage завершается ошибкой. Установка, настоящий сеанс MCP, чтение и отказ в записи проверены на macOS, Linux и Windows x64. Возможности FUSE и отдельного системного монтирования здесь не используются.

Исходный выпуск: [Mirage v0.0.6](https://github.com/strukto-ai/mirage/releases/tag/v0.0.6), редакция `5678c94557ab4d00f44b1a9b18be562ac1e643c4`.
