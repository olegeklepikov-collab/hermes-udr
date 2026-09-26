# 5. Zvec: библиотека, проверка и официальный MCP

Zvec работает в процессе Python; отдельный обязательный сервер БД не нужен. Различайте: библиотеку Zvec 0.7.0, официальный `zvec-mcp-server` 0.3.0 и встроенный FTS/BM25-адаптер Foundation. Они не являются одной службой. Для нативного пути ниже используется библиотека и официальный MCP, с отдельным каталогом индекса.

## Установка и непосредственная проверка

macOS Apple Silicon / Linux x64 или arm64:
```bash
uv venv --python 3.13 "$UDR_SOFTWARE/zvec"
uv pip install --python "$UDR_SOFTWARE/zvec/bin/python" 'zvec==0.7.0' 'zvec-mcp-server==0.3.0'
"$UDR_SOFTWARE/zvec/bin/python" "$UDR_SETUP_DIR/scripts/zvec_probe.py" "$UDR_STATE/zvec-probe-01"
```
Windows x64:
```powershell
uv venv --python 3.13 "$env:UDR_SOFTWARE\zvec"
uv pip install --python "$env:UDR_SOFTWARE\zvec\Scripts\python.exe" 'zvec==0.7.0' 'zvec-mcp-server==0.3.0'
& "$env:UDR_SOFTWARE\zvec\Scripts\python.exe" "$env:UDR_SETUP_DIR\scripts\zvec_probe.py" "$env:UDR_STATE\zvec-probe-01"
```

Ожидается JSON `status=passed`, `vector_query=true`, `fts_query=true`, `reopen_read_only=true`. Проба создаёт новый каталог, записывает синтетический вектор и текст и не вызывает модель. Она не измеряет качество семантического поиска. Повторите с другим именем каталога; не удаляйте пользовательский индекс ради пробы.

Проверен состав опубликованных Python 3.13 wheels: macOS arm64, Linux x64/arm64, Windows x64. Отсутствие wheel для macOS Intel или Windows ARM64 нельзя скрывать автоматическим переходом в другой runtime. Сборка из исходников на этих платформах не проверена этим пакетом.

## Подключение к Hermes

```yaml
mcp_servers:
  zvec:
    command: /ABSOLUTE/UDR_SOFTWARE/zvec/bin/python
    args: [-m, zvec_mcp]
    enabled: true
    tools:
      include: [open_collection, get_collection_info, fetch_documents, vector_query, multi_vector_query]
```

На Windows `command` указывает на фактический путь вида `C:/Users/ИМЯ/AppData/Local/HermesUDR/software/zvec/Scripts/python.exe`; подставьте значение `$env:UDR_SOFTWARE`, переведя обратные косые черты в прямые. Проверка: `hermes mcp list`, `hermes mcp test zvec`, затем новая сессия. `tools.include` ограничивает доступные модели инструменты, но не является ограничением доступа процесса к файловой системе.

Для обычного читателя открывайте уже созданный индекс:
```json
{"path":"/ABSOLUTE/UDR_STATE/zvec/index-v1","collection_name":"research","read_only":true}
```

На Windows значение `path` имеет вид `C:/Users/ИМЯ/AppData/Local/HermesUDR/state/zvec/index-v1`; используйте фактический `$env:UDR_STATE` и одинаковый путь во всех вызовах коллекции.

Для первоначального наполнения нужен отдельный операторский сеанс с `create_and_open_collection`, `insert_documents`/`embedding_write` и, если требуется, `create_index`. Завершите пишущий сеанс до запуска читателя. `destroy_collection`, `drop_index` и удаление документов не выдаются обычному исследовательскому профилю. Один каталог коллекции не обслуживается несколькими независимыми писателями. Предпочитайте абсолютные пути.

Векторный индекс создаётся оператором по схеме MCP, например для проверочного трёхмерного вектора:
```json
{"path":"/ABSOLUTE/UDR_STATE/zvec/index-v1","collection_name":"research","vector_fields":[{"name":"embedding","data_type":"VECTOR_FP32","dimension":3}],"scalar_fields":[{"name":"text","data_type":"STRING","nullable":false}]}
```

Для настоящих документов размерность **не 3 по умолчанию**: она определяется выбранной embedding-моделью. Зафиксируйте модель, версию, размерность, разбиение текста и способ нормализации. Входы `insert_documents` сверяйте через фактическую схему инструмента; именованные поля и vector должны соответствовать коллекции.

## Модели и ограничения подключения

Официальный MCP поддерживает ручные векторы без вызова сервиса и отдельные `embedding_*` операции через OpenAI-совместимый API. Если нужны эти операции, разрешите только необходимые имена и задайте `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_EMBEDDING_MODEL` в локальной среде запуска. Имя переменной не требует использования поставщика OpenAI, но выбранный endpoint должен поддерживать соответствующий протокол. Не записывайте ключ в общий YAML. Класс embedding-модели нужно разрешить в конкретную конфигурацию; класс reasoning-модели Hermes не является такой конфигурацией автоматически.

FTS/BM25-проверка выполняется напрямую включённым скриптом. Наличие FTS в SDK не означает, что официальный MCP предоставляет отдельный FTS-инструмент; его проверенная схема перечислена upstream. Не обещайте все сочетания hybrid/rerank через один одинаковый вызов. Векторы, FTS и объединение результатов требуют выбранной схемы, а не только `pip install`.

## Сохранение, перенос и откат

Исходные документы сохраняются отдельно от индекса. Остановите все процессы, открывшие коллекцию, затем копируйте её каталог и конфигурацию в новый резервный каталог. Восстанавливайте в новый путь и повторяйте поиск фиксированного проверочного документа. При смене embedding-модели/размерности создайте новое поколение; старое сохраняйте до проверки нового. Нельзя использовать каталог native MCP одновременно как коллекцию внутреннего Foundation: форматы журналов и принятия записей различаются.

Источники: [Zvec 0.7.0](https://zvec.org/en/blog/2026-08-25-zvec-release/), [матрица платформ](https://zvec.org/en/blog/2026-09-17-zvec-multi-platform/), [точный MCP исходник](https://github.com/zvec-ai/zvec-mcp-server/tree/0287aa883974f2f7602468bec796cad6178952a7), [Python-пакет](https://pypi.org/project/zvec-mcp-server/0.3.0/).
