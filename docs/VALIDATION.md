# Проверка реализации

Дата: 28 сентября 2026. Windows, Python 3.13.12.

| Проверка | Результат |
|---|---|
| `python -m pytest -q` | 59 тестов прошли |
| `python -m ruff check .` | Без ошибок |
| `python -m mypy` | Без ошибок, 23 файла модуля |
| `python -m pip check` | Конфликтов зависимостей нет |
| Crawl dry-run, 10 URL | 10 страниц + robots.txt, ошибок нет |
| Реальные страницы → raw → parsing → chunks | 5 документов, 39 chunks |
| PDF/DOCX → Qdrant в тестах | Настоящий embedded Qdrant; тестовый embedder |
| OpenAI адаптер → PDF → Qdrant | Подменённый SDK-клиент, без внешних API-запросов |
| Полный smoke с OpenAI API | Не выполнен: OPENAI_API_KEY не задан |

Подготовленные данные находятся локально в `data/raw`, `data/parsed` и
`data/registry.sqlite3`, исключены из Git. Все пять документов имеют статус
`pending`, то есть ожидают индексации:

| Страница КБТУ | Chunks |
|---|---:|
| Документы для обучающихся | 3 |
| Справочник студента / ресурсы | 6 |
| Общежитие | 10 |
| Научная библиотека | 6 |
| Student Life | 14 |

В этом ограниченном запуске сохранены только пять стартовых HTML-страниц.
PDF/DOCX по их ссылкам ещё не скачивались. Для продолжения:

```bash
python -m ingestion.cli crawl-kbtu --parse-only
python -m ingestion.cli ingest-folder data/inbox/telegram --parse-only
```

После указания `OPENAI_API_KEY` в `.env` и настройки общего Qdrant:

```bash
python -m ingestion.cli reindex-all
python -m ingestion.cli verify
```

Первоначальная страница `/ru/studentam/` вернула HTTP 404, поэтому crawler
стартует с конкретных студенческих разделов. При последующих сетевых сбоях
проверена обработка ошибок; недоступный robots.txt блокирует запросы хоста.

Тесты проверяют парсинг, таблицы, страницы и parent-контекст, binary/content
deduplication, версии и доверие, явные даты, смешанные языки, фильтры Qdrant,
лексический поиск номера документа, восстановление после частичной записи,
повреждённый PDF в batch, dry-run, scope/redirects, robots.txt, backoff и режим
подготовки без embeddings. Они не являются оценкой качества ответов RAG.

Адаптер OpenAI дополнительно проверяется на пакетную отправку, маскировку текста,
порядок и размерность векторов, ограничения длины и безопасные сообщения об ошибках.
Эти проверки подменяют SDK-клиент и не оценивают качество реальных embeddings.

OpenAI API, OCR с Tesseract и production-сервер Qdrant в этом окружении не проверялись.
После настройки ключа можно запустить `python scripts/smoke_ingestion.py`;
синтетический PDF хранится отдельно в `data/smoke-openai`.
