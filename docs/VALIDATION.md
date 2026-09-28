# Проверка реализации

Дата: 28 сентября 2026. Windows, Python 3.13.12.

| Проверка | Результат |
|---|---|
| `python -m pytest -q` | 71 тест прошёл |
| `python -m ruff check .` | Без ошибок |
| `python -m mypy` | Без ошибок, 24 файла ingestion |
| `python -m pip check` | Конфликтов зависимостей нет |
| Crawl dry-run, 10 URL | 10 страниц + robots.txt, ошибок нет |
| Реальные страницы → raw → parsing → chunks | 5 документов, 39 chunks |
| PDF/DOCX → Qdrant в тестах | Настоящий embedded Qdrant; тестовый embedder |
| OpenAI адаптер → PDF → Qdrant | Подменённый SDK-клиент, без внешних API-запросов |
| Полный smoke с OpenAI API | Не выполнен: OPENAI_API_KEY не задан |
| `npm --prefix frontend run build` | TypeScript + Vite успешно, 2144 модуля |
| API → ingestion → persistent Qdrant → поиск → SSE | 7 тестов приложения, OpenAI подменён |
| TXT/Markdown/CSV/XLSX → общий pipeline | 5 тестов форматов |
| Реальный HTTP backend и собранный frontend | `/` и `/api/health` возвращают 200 |
| Chromium / Playwright | UI базы знаний показывает 5 pending-документов; токенизация, SSE и мобильная ширина проверены, ошибок JavaScript нет |

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

При embedded Qdrant сначала остановите backend. Через интерфейс тот же импорт
выполняется кнопкой «Обновить базу» при работающем сервере.

API-тесты проверяют загрузку, дедупликацию без повторного запроса embeddings,
исключение unverified из поиска, подтверждение/отзыв доверия, цитаты со страницами,
SSE-ответ, скачивание оригинала, архивирование без удаления raw, индексацию pending
после появления ключа, защиту схемы при смене модели и сохранение crawler-источников
при синхронизации пустого inbox. Локальный браузерный smoke сохранён в
`data/validation`, исключён из Git; тесты API находятся в `tests/test_application.py`.

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
