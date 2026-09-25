# Установка подписанной беты

[Главная](../../README.ru.md) · [English](../en/installation.md)

Используйте новый профиль. Пакет не заменяет работающий Hermes и не настраивает ваши ключи. Требуется совместимый Hermes; проверенная основа — 0.21.3, commit `2034126e0d1f397b4612782156097243dbbdc819`. Исходный выпуск Foundation содержит отдельную поправку проверки Telegram-кнопок; применение к другой редакции требует проверки совместимости. Внутренние ID остаются `ultra-deep-research` и `hermes-foundation-bridge`.

Python ≥3.11; проверены Python 3.13, macOS и Linux arm64. Для PDF требуется Poppler либо `pdfplumber==0.11.9`. Hermes не устанавливает зависимости плагина автоматически. Подключения сервисов, API/OAuth и модель задаются в профиле пользователя. Для Foundation нужны Beads 1.1.0, Dolt 2.2.1 и его дополнительные зависимости, а также службы из закреплённого bridge-lock.json.

## Проверка поставки

Доверенный открытый ключ имеет SHA-256 `2295aaab3cb418c4f81a867a701a8187e8cdd0f73105a1f318c1faf981dfdb1a`; сверяйте его через независимый доверенный канал, в том числе предыдущую опубликованную линию. Ключ, скачанный вместе с архивом, сам по себе не устанавливает доверие. Нужны GitHub CLI, Minisign и unzip.
```sh
export HERMES_HOME="$HOME/.hermes-udr-beta"
export HERMES_FOUNDATION_ROOT="$HERMES_HOME/foundation"
mkdir hermes-udr-download
cd hermes-udr-download
gh release download v0.44.0-beta.1 --repo olegeklepikov-collab/hermes-udr
minisign -Vm SHA256SUMS -p release-signing.pub
shasum -a 256 -c SHA256SUMS
minisign -Vm hermes-research-report-0.44.0b1.zip -p release-signing.pub
minisign -Vm hermes-foundation-bridge-0.13.0b1.zip -p release-signing.pub
unzip -n hermes-research-report-0.44.0b1.zip -d research-source
unzip -n hermes-foundation-bridge-0.13.0b1.zip -d foundation-source
```

## Установка из проверенных байтов

Предварительно настройте имя и почту автора локального Git. Коммит локального установочного источника будет отличаться от коммита разработки; состав архива определяется его манифестом.
```sh
python3 - <<'PYCODE'
import json, subprocess
from pathlib import Path
for folder in ("research-source", "foundation-source"):
    root = Path(folder).resolve()
    manifest = json.loads((root / "bundle-manifest.json").read_text())
    files = [row["path"] for row in manifest["files"]] + ["bundle-manifest.json"]
    subprocess.run(["git", "-C", str(root), "init", "-b", "release"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "--", *files], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "Verified Hermes UDR beta package"], check=True)
PYCODE
UDR_REF="$(git -C research-source rev-parse HEAD)"
FOUNDATION_REF="$(git -C foundation-source rev-parse HEAD)"
hermes plugins install "file://$PWD/research-source" --ref "$UDR_REF" --no-enable
hermes plugins install "file://$PWD/foundation-source" --ref "$FOUNDATION_REF" --no-enable
hermes plugins doctor ultra-deep-research --ci
hermes plugins doctor hermes-foundation-bridge --ci
hermes plugins enable ultra-deep-research --no-allow-tool-override
```

Для автономного Research достаточно первого плагина: задайте класс модели и запустите `python "$HERMES_HOME/plugins/ultra-deep-research/skills/research/scripts/run_research.py" --question "Ваш вопрос" --mode research`. Foundation необязателен для этого пути.

## Управляемый запуск

Перед включением Foundation подготовьте его службы по `components/foundation/README.md` и `DOLT_SQL.md`. Сохраните полные каталоги плагинов. Добавьте их `src` в PYTHONPATH управляющего Python-сеанса. Укажите `research.integration_mode: foundation` и абсолютный `research.workspace_root` в конфигурации выбранного профиля. Настройте разрешённые операции поставщиков через `research.web_provider_allowlist`; пустая таблица блокирует универсальный выбор поставщика, а не регистрацию новых сервисов.

Существующий управляющий сеанс создаёт ResearchWorkContractV1, получает задачу/аренду и вызывает `run_in_host` на своём AIAgent. Модель не назначает себе допуск. Пример — [интерфейсы Foundation](../reference/foundation.md). Настройка контейнерного терминала не изолирует Python плагина: в режиме foundation исходные файлы обрабатывает отдельный разрешённый обработчик.

Подпись не включает службы и не активирует экземпляр автоматически. Копируйте Foundation ZIP, его .minisig и открытый ключ в `$HERMES_FOUNDATION_ROOT/releases/hermes-foundation-bridge-0.13.0b1/`, затем проверяйте `foundation_release_verify` с версией 0.13.0b1 и исходным commit из манифеста пакета. Производственное включение остаётся решением владельца экземпляра.
