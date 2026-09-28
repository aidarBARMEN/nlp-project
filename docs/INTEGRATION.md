# Контракт для backend KBTU Smart Assistant

Партнёр реализует API, frontend, Telegram-бота, retrieval/reranking и генерацию.
Этот пакет готовит источники и индекс. Он не запускает сервер приложения.

## Общая коллекция

Согласуйте `QDRANT_URL`, `QDRANT_COLLECTION`, `EMBEDDING_MODEL` и `EMBEDDING_DIMENSIONS`.
Embeddings создаются через OpenAI API с `OPENAI_API_KEY` в окружении или `.env`.
По умолчанию: `text-embedding-3-small`, 1536 измерений.
Все источники пишутся в одну коллекцию. Имена векторов:

| Имя | Формат | Как построить запрос |
|---|---|---|
| `dense` | cosine, размерность модели | `create_embedder(settings).query(text)` |
| `sparse` | stable hashed lexical TF | `lexical_vector(text)` |

Sparse — воспроизводимый лексический TF-поиск с `1 + log(count)`, без BM25 IDF.
Он сохраняет `GPA`, `FX`, `Retake`, `WSP`, `Uninet`, `Add/Drop`, `51-2-25`.
32-битное хеширование допускает редкие коллизии. Используйте ту же реализацию для
запросов; нельзя смешивать её со sparse-весами другой модели.

`create_embedder` возвращает `OpenAIEmbedder`: метод `query(text)` использует ту же
модель и размерность, что и документы, без дополнительных префиксов. Адаптер
маскирует базовые персональные данные перед отправкой текста в API.
Создайте его один раз на процесс для переиспользования HTTP-клиента, а при остановке
вызовите `close()`. Конструктор и чтение размерности не выполняют API-запросов.
Смена модели или размерности требует новой коллекции и `reindex-all`.

## Обязательные фильтры

```python
from ingestion.services.indexer import knowledge_filter

# Публичные ответы по действующим официальным документам:
filters = knowledge_filter()
# Исторические ответы (включает current и архив):
historical = knowledge_filter(current=None, academic_year="2024-2025")
```

Фильтр включает `record_type=chunk`, `index_status=ready`, `is_current=true` и
`trust_level=official`. `verified_internal` добавляйте только после авторизации
пользователя в backend. Это не публичные документы по умолчанию. `unverified`
доступны в индексе для проверки оператором, но не должны попадать в официальные
ответы. Нельзя делать unfiltered search: в коллекции также есть служебная точка
`record_type=configuration`, защищающая от смешивания embedding-моделей.

Поддерживаются фильтры `academic_year`, `language`, `category`, `source_channel`,
`target_audience`, `doc_id`, `is_current`, `trust_level`.
Для mixed-language документов language=`mixed`, список языков хранится в canonical
metadata; не ограничивайте запрос языком пользователя без необходимости.

## Payload и цитаты

Каждый chunk содержит:

```text
chunk_id, doc_id, text, title, section, subsection
page_start, page_end, document_number
source_url, source_channel, fetched_at
language, category, target_audience, academic_year, version
effective_from, effective_to, is_current, supersedes_doc_id, trust_level
parent_chunk_id, metadata, embedding_signature, index_status, record_type
```

PDF-страницы нумеруются с 1; у HTML/DOCX номера страниц null, поскольку реальная
пагинация неизвестна. Цитата: title + document_number + section + page_start/end
+ source_url. Для локального документа без URL ссылку на файл должен формировать
backend после проверки доступа; не отдавайте пользователю внутренний raw_path.

Parent по `parent_chunk_id` доступен в
`data/parsed/<doc_id>.json → parsed.metadata.parents`. Доступ к этому файлу
ограничивается на стороне backend. Актуальные trust/version/current смотрите
в payload или реестре, а не в сохранённом parsed-снимке.

## Передача файлов из Telegram

После своей проверки `user_id in ADMIN_TELEGRAM_IDS` бот сохраняет PDF/DOCX в
inbox и отправляет задание одному ingestion worker. Токены/авторизация остаются
в backend. CLI worker:

```bash
python -m ingestion.cli ingest-file path/to/document.pdf --source-channel telegram
```

Вывод stdout — JSON; логи идут в stderr. Статусы: `processed`, `duplicate`,
`needs_ocr`, `failed`; внутренние этапы представлены в реестре состоянием
`processing`. Из `doc_id` можно получить данные для ответа через `inspect`.
Подтверждение официальности — отдельное действие администратора `set-trust`.

## Эксплуатационные границы

Один ingestion worker и постоянный DATA_DIR. Для совместной работы с backend
нужен серверный Qdrant, а не embedded path. Backend не должен изменять реестр или
индекс ingestion напрямую. Обновление выполняется отдельным запланированным
процессом `scripts/refresh.py`; генерация ответов от него не зависит.
