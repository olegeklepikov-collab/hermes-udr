# Дополнение: локальная наблюдаемость Hermes через OTel Collector и Phoenix

Инструкция ставит приложения нативно: без Docker и без изменения установленного Hermes. Программы и конфигурация находятся в `$UDR_SOFTWARE/observability`, данные Phoenix — в `$UDR_STATE/observability/phoenix-data`. Сохраняйте уже заданные `UDR_SOFTWARE`, `UDR_STATE`, `HERMES_HOME` и `UDR_WORKSPACE` из раздела 01.

## Что поддерживает закреплённый Hermes

В закреплённом исходнике `projects/hermes-e2e44-stand/hermes-source` есть экспорт `monitoring.gateway_health_export` по OTLP/HTTP. После явного включения он передаёт ограниченные события состояния шлюза и cron в виде трасс, а также метрики и диагностические записи. Это **не** автоматическая трассировка вызовов модели, содержимого переписки и результатов инструментов. В документации Hermes они прямо отделены от мониторинга шлюза; не следует считать установленный Collector их интеграцией.

В существующий `$HERMES_HOME/config.yaml` добавьте, сохранив остальные настройки:

```yaml
monitoring:
  gateway_health_export:
    enabled: true
  export:
    otlp:
      enabled: true
      endpoint: http://127.0.0.1:4318/v1/traces
      headers_env: {}
```

На нативной установке Hermes должен иметь необязательную зависимость `hermes-agent[otlp]` (в закреплённом исходнике версия SDK и HTTP exporter — `1.39.1`). Устанавливайте extra в среду Hermes, а не в отдельное окружение Phoenix. Без SDK экспорт не включится.

## Подготовка Collector и Phoenix

Закреплены выпуски, опубликованные официальными проектами: OpenTelemetry Collector Contrib `0.161.0` (16.09.2026) и Arize Phoenix `20.16.0` (23.09.2026). В релизе Collector есть нативные архивы Linux, macOS и Windows; имена строятся по схеме `otelcol-contrib_0.161.0_<os>_<arch>.tar.gz`. Поддерживаемые этой памяткой варианты: `linux_amd64`, `linux_arm64`, `darwin_amd64`, `darwin_arm64`, `windows_amd64`.

На macOS/Linux в оболочке, где доступны заданные переменные:

```bash
export OBS_DIR="$UDR_SOFTWARE/observability"
export OBS_STATE="$UDR_STATE/observability"
export UDR_OBSERVABILITY_DIR="$OBS_DIR"
mkdir -p "$OBS_DIR/bin" "$OBS_STATE/phoenix-data"
cd "$OBS_DIR"
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  target=linux_amd64 ;;
  Linux-aarch64) target=linux_arm64 ;;
  Darwin-x86_64) target=darwin_amd64 ;;
  Darwin-arm64)  target=darwin_arm64 ;;
  *) echo "Нет указанного архива Collector для этой архитектуры" >&2; exit 1 ;;
esac
archive="otelcol-contrib_0.161.0_${target}.tar.gz"
url="https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.161.0/$archive"
curl -fL "$url" -o "$archive"
curl -fL "$url.sha256" -o "$archive.sha256"
"$HERMES_PYTHON" - "$archive" "$archive.sha256" <<'PY'
import hashlib, pathlib, sys
expected = pathlib.Path(sys.argv[2]).read_text(encoding="ascii").strip().lower()
actual = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected) or actual != expected:
    raise SystemExit("Collector SHA-256 не совпал")
PY
tar -xzf "$archive" -C "$OBS_DIR/bin" otelcol-contrib
```

На Windows 64-bit откройте PowerShell. Python 3.11 создаётся отдельно через uv; он не заменяет Python Hermes:

```powershell
$obs = Join-Path $env:UDR_SOFTWARE 'observability'
$obsState = Join-Path $env:UDR_STATE 'observability'
$env:UDR_OBSERVABILITY_DIR = $obs
New-Item -ItemType Directory -Force "$obs\bin", "$obsState\phoenix-data" | Out-Null
$archive = 'otelcol-contrib_0.161.0_windows_amd64.tar.gz'
$url = "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.161.0/$archive"
Invoke-WebRequest $url -OutFile (Join-Path $obs $archive)
Invoke-WebRequest "$url.sha256" -OutFile (Join-Path $obs "$archive.sha256")
$expected = (Get-Content (Join-Path $obs "$archive.sha256") -Raw).Trim().ToLowerInvariant()
$actual = (Get-FileHash (Join-Path $obs $archive) -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expected -notmatch '^[0-9a-f]{64}$' -or $actual -ne $expected) { throw 'Collector SHA-256 не совпал' }
tar -xzf (Join-Path $obs $archive) -C (Join-Path $obs 'bin') otelcol-contrib.exe
uv python install 3.11
uv venv --seed --python 3.11 (Join-Path $obs 'phoenix-venv')
& (Join-Path $obs 'phoenix-venv\Scripts\python.exe') -m pip install 'arize-phoenix==20.16.0'
```

На macOS/Linux создайте изолированную среду Phoenix:

```bash
uv python install 3.11
uv venv --seed --python 3.11 "$OBS_DIR/phoenix-venv"
"$OBS_DIR/phoenix-venv/bin/python" -m pip install 'arize-phoenix==20.16.0'
```

## Конфигурация и локальный запуск

Сохраните следующий файл как `$UDR_SOFTWARE/observability/collector.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:4318

exporters:
  otlp_http/phoenix:
    endpoint: http://127.0.0.1:6006
  debug:
    verbosity: basic

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlp_http/phoenix]
    metrics:
      receivers: [otlp]
      exporters: [debug]
    logs:
      receivers: [otlp]
      exporters: [debug]
```

Phoenix принимает OTLP/HTTP трассы на `127.0.0.1:6006/v1/traces`; его веб-интерфейс доступен на `http://127.0.0.1:6006`. SQLite-файлы сохраняются в `$UDR_STATE/observability/phoenix-data`, заданном через `PHOENIX_WORKING_DIR`. Collector привязан к локальному `127.0.0.1:4318`; gRPC-порт не нужен. Метрики и журналы Hermes принимаются Collector, но направляются в его вывод `debug` — Phoenix здесь используется только для трасс.

Сначала запустите Phoenix, затем Collector. Оба процесса пока остаются в переднем плане своих терминалов.

macOS/Linux, Phoenix:

```bash
OBS_DIR="$UDR_SOFTWARE/observability"
OBS_STATE="$UDR_STATE/observability"
PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=6006 PHOENIX_WORKING_DIR="$OBS_STATE/phoenix-data" \
  "$OBS_DIR/phoenix-venv/bin/phoenix" serve
```

macOS/Linux, Collector (проверка конфигурации перед запуском):

```bash
OBS_DIR="$UDR_SOFTWARE/observability"
"$OBS_DIR/bin/otelcol-contrib" validate --config="$OBS_DIR/collector.yaml"
"$OBS_DIR/bin/otelcol-contrib" --config="$OBS_DIR/collector.yaml"
```

Windows PowerShell, в двух окнах:

```powershell
$obs = Join-Path $env:UDR_SOFTWARE 'observability'
$env:PHOENIX_HOST = '127.0.0.1'
$env:PHOENIX_PORT = '6006'
$env:PHOENIX_WORKING_DIR = Join-Path $env:UDR_STATE 'observability\phoenix-data'
& (Join-Path $obs 'phoenix-venv\Scripts\phoenix.exe') serve
```

```powershell
$obs = Join-Path $env:UDR_SOFTWARE 'observability'
& (Join-Path $obs 'bin\otelcol-contrib.exe') validate --config (Join-Path $obs 'collector.yaml')
& (Join-Path $obs 'bin\otelcol-contrib.exe') --config (Join-Path $obs 'collector.yaml')
```

Откройте `http://127.0.0.1:6006`; затем перезапустите Hermes. Сверьте статус через `hermes monitoring status`. На хосте порт Collector доступен только локальным процессам. Проверка с самого компьютера: `curl http://127.0.0.1:4318/` может вернуть `404` — это не проверка приёма трасс; используйте состояние Collector и появление новых трасс в Phoenix.

## Автозапуск и границы официальной поддержки

Перед генерацией пользовательской службы задайте `UDR_OBSERVABILITY_DIR` абсолютным путём `$UDR_SOFTWARE/observability`. Не меняйте `UDR_SOFTWARE`, `UDR_STATE` и `HERMES_HOME`; передавайте их службе как есть. `cwd` обоих процессов — `$UDR_OBSERVABILITY_DIR`.

| Процесс | macOS/Linux `argv` | Windows `argv` | Дополнительные переменные среды |
|---|---|---|---|
| Phoenix | `[$UDR_OBSERVABILITY_DIR/phoenix-venv/bin/phoenix, serve]` | `[$UDR_OBSERVABILITY_DIR/phoenix-venv/Scripts/phoenix.exe, serve]` | `PHOENIX_HOST=127.0.0.1`; `PHOENIX_PORT=6006`; `PHOENIX_WORKING_DIR=$UDR_STATE/observability/phoenix-data` |
| Collector | `[$UDR_OBSERVABILITY_DIR/bin/otelcol-contrib, --config=$UDR_OBSERVABILITY_DIR/collector.yaml]` | `[$UDR_OBSERVABILITY_DIR/bin/otelcol-contrib.exe, --config=$UDR_OBSERVABILITY_DIR/collector.yaml]` | нет |

Обе службы также должны наследовать `UDR_SOFTWARE`, `UDR_STATE`, `HERMES_HOME`, `UDR_OBSERVABILITY_DIR`. Подставляйте абсолютные пути при рендеринге `launchd` LaunchAgent, `systemd --user` unit или Windows Task Scheduler; оставляйте каждую программу отдельным долгоживущим процессом. До регистрации проверьте Collector: `otelcol-contrib validate --config=$UDR_OBSERVABILITY_DIR/collector.yaml` (для Windows исполняемый файл `.exe`).

OpenTelemetry публикует бинарники для этих платформ, но выбранная Contrib-сборка не регистрирует их как службы. У Phoenix официально описаны команда `phoenix serve` и её настройки через переменные среды, но не готовые unit/plist/задачи. Это шаблоны параметров для встроенного менеджера установки, а не upstream-установщики. В изученной документации Phoenix нет явной матрицы поддержки нативной установки по ОС; Windows CLI не следует выдавать за отдельно подтверждённый Arize сервис.

## Резервная копия и восстановление без перезаписи

Сначала штатно остановите Phoenix. Collector можно остановить отдельно; он не хранит трассы на диске, поэтому архивировать нужно каталог `$UDR_STATE/observability/phoenix-data`. Для macOS/Linux оболочки резервная копия с проверкой архива:

```bash
OBS_STATE="$UDR_STATE/observability"
mkdir -p "$UDR_WORKSPACE/backups"
backup="$UDR_WORKSPACE/backups/phoenix-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
set -o noclobber
tar -czf "$backup" -C "$OBS_STATE/phoenix-data" .
tar -tzf "$backup" >/dev/null
```

В PowerShell используйте системный `tar.exe`, чтобы включить скрытые файлы рабочего каталога, которые `Compress-Archive` пропускает:

```powershell
$obsState = Join-Path $env:UDR_STATE 'observability'
$backups = Join-Path $env:UDR_WORKSPACE 'backups'
New-Item -ItemType Directory -Force $backups | Out-Null
$archive = Join-Path $backups ("phoenix-{0}.tar.gz" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
if (Test-Path $archive) { throw 'Архив уже существует' }
& tar.exe -czf $archive -C (Join-Path $obsState 'phoenix-data') .
if ($LASTEXITCODE -ne 0) { throw 'Архив не создан' }
& tar.exe -tzf $archive | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Архив не читается' }
```

Восстанавливайте только в новый каталог, не поверх оригинала. macOS/Linux: задайте архив и новый, ещё не существующий путь; после извлечения явно задайте его как `PHOENIX_WORKING_DIR` для проверки.

```bash
OBS_STATE="$UDR_STATE/observability"
restore="$OBS_STATE/phoenix-data-restore-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$restore"
tar -xzf "$UDR_WORKSPACE/backups/phoenix-<timestamp>.tar.gz" -C "$restore"
# Для проверочного запуска Phoenix задайте PHOENIX_WORKING_DIR="$restore".
```

PowerShell:

```powershell
$obsState = Join-Path $env:UDR_STATE 'observability'
$restore = Join-Path $obsState ("phoenix-data-restore-{0}" -f (Get-Date -Format 'yyyyMMddTHHmmssZ'))
if (Test-Path $restore) { throw 'Каталог восстановления уже существует' }
New-Item -ItemType Directory -ErrorAction Stop $restore | Out-Null
& tar.exe -xzf (Join-Path $env:UDR_WORKSPACE 'backups\phoenix-<timestamp>.tar.gz') -C $restore
if ($LASTEXITCODE -ne 0) { throw 'Восстановление архива не завершено' }
# Для проверочного запуска Phoenix задайте $env:PHOENIX_WORKING_DIR = $restore.
```

## Официальные источники

- [OpenTelemetry Collector Contrib: релиз 0.161.0 и нативные файлы](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.161.0)
- [OpenTelemetry Collector: поддержка платформ](https://github.com/open-telemetry/opentelemetry-collector/blob/main/docs/platform-support.md)
- [OpenTelemetry Collector: конфигурация, loopback и команды проверки](https://opentelemetry.io/docs/collector/configuration/)
- [OpenTelemetry Collector: HTTP exporter и правила формирования путей](https://github.com/open-telemetry/opentelemetry-collector/blob/main/exporter/otlphttpexporter/README.md)
- [Phoenix: релиз 20.16.0](https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v20.16.0)
- [Phoenix: порты, переменные среды, хранение и запуск](https://arize.com/docs/phoenix/self-hosting/configuration)
- [Phoenix: установка через терминал](https://arize.com/docs/phoenix/self-hosting/deployment-options)
- Локальный закреплённый источник Hermes: `projects/hermes-e2e44-stand/hermes-source/website/docs/developer-guide/gateway-monitoring.md`, `agent/monitoring/otlp_exporter.py`, `agent/monitoring/gateway_health_export.py`, `hermes_cli/config_defaults.py`.
