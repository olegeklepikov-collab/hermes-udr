# 1. Нативная основа и Hermes

Никакие команды этого пакета не устанавливают Docker и не используют WSL. Выберите один путь ниже. Подготовка новых файлов не меняет работающий экземпляр. Права администратора нужны только для системных пакетов; Hermes запускается обычным пользователем.

## 1.1. Каталоги и переменные

Распакуйте комплект. Откройте терминал в его корне. Выберите новые каталоги; если каталог профиля уже содержит действующие настройки, остановитесь и выберите другой.

macOS и Linux (bash/zsh):
```bash
export UDR_SETUP_DIR="$PWD"
export UDR_SOFTWARE="$HOME/.local/share/hermes-udr-native/software"
export UDR_STATE="$HOME/.local/share/hermes-udr-native/state"
export UDR_WORKSPACE="$HOME/hermes-udr-work"
export HERMES_HOME="$HOME/.hermes-udr-native"
export HERMES_FOUNDATION_ROOT="$HERMES_HOME/foundation"
mkdir -p "$UDR_SOFTWARE" "$UDR_STATE" "$UDR_WORKSPACE"
```

Windows x64, PowerShell:
```powershell
$env:UDR_SETUP_DIR = (Get-Location).Path
$env:UDR_SOFTWARE = Join-Path $env:LOCALAPPDATA 'HermesUDR\software'
$env:UDR_STATE = Join-Path $env:LOCALAPPDATA 'HermesUDR\state'
$env:UDR_WORKSPACE = Join-Path $env:USERPROFILE 'HermesUDR-work'
$env:HERMES_HOME = Join-Path $env:USERPROFILE '.hermes-udr-native'
$env:HERMES_FOUNDATION_ROOT = Join-Path $env:HERMES_HOME 'foundation'
New-Item -ItemType Directory -Force $env:UDR_SOFTWARE,$env:UDR_STATE,$env:UDR_WORKSPACE | Out-Null
```

Переменные относятся к текущему терминалу; при повторном входе задайте их снова. Параметры автозапуска сохраняются в явных файлах служб из раздела 08. `HOME`/`USERPROFILE` не переназначаются. Foundation хранит профили в родительском каталоге своего корня; поэтому `HERMES_FOUNDATION_ROOT` расположен непосредственно внутри `HERMES_HOME`.

## 1.2. Системные пакеты

macOS (установленный Homebrew):
```bash
brew install git uv node@24 sqlite minisign
export PATH="$(brew --prefix node@24)/bin:$PATH"
```
Если Homebrew отсутствует, установите его по [официальной инструкции](https://brew.sh/), затем повторите команды. Проверка: `git --version`, `uv --version`, `node --version`, `npm --version`, `minisign -v`. Не удаляйте системные SQLite или Python.

Linux, Ubuntu 24.04:
```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates unzip xz-utils build-essential python3-venv sqlite3 libsqlite3-dev minisign libmagic1 poppler-utils
python3 -m venv "$UDR_SOFTWARE/bootstrap"
"$UDR_SOFTWARE/bootstrap/bin/python" -m pip install 'uv==0.12.19'
export PATH="$UDR_SOFTWARE/bootstrap/bin:$PATH"
```
Node устанавливается отдельным официальным архивом версии 24.18.0: скачайте для своей архитектуры файл и `SHASUMS256.txt` с `https://nodejs.org/dist/v24.18.0/`, затем выполните:
```bash
# x86_64; для aarch64 замените linux-x64 на linux-arm64.
cd "$UDR_SOFTWARE"
curl -fLO https://nodejs.org/dist/v24.18.0/node-v24.18.0-linux-x64.tar.xz
curl -fLO https://nodejs.org/dist/v24.18.0/SHASUMS256.txt
sha256sum --ignore-missing -c SHASUMS256.txt
tar -xf node-v24.18.0-linux-x64.tar.xz
export PATH="$UDR_SOFTWARE/node-v24.18.0-linux-x64/bin:$PATH"
node --version
npm --version
```
Ожидается `v24.18.0`. Не подменяйте этот шаг Ubuntu-пакетом Node 18: сервер TypeScript Serena требует Node ≥20. Проверенный SHA-файл нужно получить из доверенного официального источника; обычная сумма не является подписью издателя.

Windows, PowerShell:
```powershell
winget install --exact --id Git.Git --accept-package-agreements --accept-source-agreements
winget install --exact --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
winget install --exact --id astral-sh.uv --accept-package-agreements --accept-source-agreements
winget install --exact --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
```
Откройте новый PowerShell, повторно задайте переменные из 1.1 и проверьте `git --version`, `py -3.13 --version`, `uv --version`, `node --version`, `npm --version`. Требуется Node ≥20; зафиксируйте реально установленную версию. Это не инструкция применять глобальную политику `ExecutionPolicy Bypass`. При запрете npm.ps1 используйте `npm.cmd`.

## 1.3. Закреплённый Hermes

На всех ОС выполняются команды Git/uv. В PowerShell пути подставляются через `$env:UDR_SOFTWARE`, а не bash-синтаксис `$UDR_SOFTWARE`:

macOS/Linux:
```bash
git clone --filter=blob:none https://github.com/NousResearch/hermes-agent.git "$UDR_SOFTWARE/hermes"
git -C "$UDR_SOFTWARE/hermes" checkout --detach 2034126e0d1f397b4612782156097243dbbdc819
cd "$UDR_SOFTWARE/hermes"
uv sync --frozen --python 3.13 --extra mcp --extra messaging --extra otlp
export HERMES_PYTHON="$UDR_SOFTWARE/hermes/.venv/bin/python"
export PATH="$UDR_SOFTWARE/hermes/.venv/bin:$PATH"
hermes --version
hermes setup
```
Windows:
```powershell
git clone --filter=blob:none https://github.com/NousResearch/hermes-agent.git "$env:UDR_SOFTWARE\hermes"
git -C "$env:UDR_SOFTWARE\hermes" checkout --detach 2034126e0d1f397b4612782156097243dbbdc819
Set-Location "$env:UDR_SOFTWARE\hermes"
uv sync --frozen --python 3.13 --extra mcp --extra messaging --extra otlp
$env:HERMES_PYTHON = "$env:UDR_SOFTWARE\hermes\.venv\Scripts\python.exe"
$env:PATH = "$env:UDR_SOFTWARE\hermes\.venv\Scripts;$env:PATH"
hermes --version
hermes setup
```

В диалоге настройки выберите свой поставщик/модель либо поддержанный OAuth. Здесь нет обязательной коммерческой модели. Учётные данные вводятся локально, не в документах или переписке. Проверьте один короткий ответ `hermes chat` прежде подключения остальных сервисов. Для изменения модели используйте штатную настройку Hermes; классы Research описаны в документации подписанного выпуска.

## 1.4. Research и Foundation

Пара Research и Foundation устанавливается из одного подписанного выпуска. Точный тег и контрольные суммы находятся в `reference/native-tools.lock.json`. Последовательность проверки подписей, установки и настройки нативных служб — в [разделе 10](10-research-and-verification.md).

Research может работать самостоятельно (`research.integration_mode: standalone`) со штатными инструментами Hermes/MCP. Управляемый маршрут (`foundation`) дополнительно связывает исследование с задачей Beads, арендой, состоянием Dolt, исходными материалами, памятью и графом. Для него сначала устанавливаются службы из разделов 03, 04 и 09, затем создаётся `native-runtime.json`.

## 1.5. Проверка пределов платформы

- macOS Apple Silicon: есть wheel Zvec 0.7.0 для Python 3.13.
- Linux x64/arm64: есть соответствующие wheels.
- Windows x64: есть официальный wheel; нативные проверки выполняются на Windows x64 в GitHub Actions. Проверка выбранных пользователем поставщиков выполняется после их настройки.
- macOS Intel и Windows ARM64: не следует обещать Python-окружение Zvec 0.7.0 той же команды — соответствующих готовых wheels в проверенном наборе нет. Нативная сборка из исходников является отдельной работой, не скрытым запасным маршрутом этой инструкции.

Источники: [Hermes, закреплённый исходник](https://github.com/NousResearch/hermes-agent/tree/2034126e0d1f397b4612782156097243dbbdc819), [uv](https://docs.astral.sh/uv/getting-started/installation/), [Node 24.18.0](https://nodejs.org/dist/v24.18.0/), [Zvec: матрица платформ](https://zvec.org/en/blog/2026-09-17-zvec-multi-platform/).
