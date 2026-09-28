# Подготовка базы знаний КБТУ

Это отдельная часть data engineering. Модуль не содержит FastAPI, UI, чат-бота,
LLM-генерации или авторизации пользователей. Интеграционный контракт для партнёра
находится в [INTEGRATION.md](INTEGRATION.md).

## Установка

Python 3.11+. Выполняйте команды из корня репозитория.

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[app,dev]"
```

Скопируйте `.env.example` в `.env` (PowerShell: `Copy-Item .env.example .env`).
Укажите свой ключ OpenAI только в `.env` или переменных окружения:

```env
OPENAI_API_KEY=your-api-key
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
```

Индексация использует OpenAI embeddings API. Веса моделей локально не скачиваются.
По умолчанию размерность `text-embedding-3-small` — 1536; можно выбрать
`text-embedding-3-large` (3072) или уменьшить размерность через `EMBEDDING_DIMENSIONS`.
Документы и поисковые запросы должны использовать одинаковую модель и размерность.
Эти параметры описаны в [руководстве OpenAI](https://developers.openai.com/api/docs/guides/embeddings).

`EMBEDDING_BATCH_SIZE` задаёт размер пакета (по умолчанию 8), `OPENAI_TIMEOUT` —
таймаут запроса в секундах (60), `OPENAI_MAX_RETRIES` — число повторов SDK (3).
Адаптер проверяет длину текстов и пакетов, размерность и порядок ответов API.
Парсинг и `--parse-only` работают без ключа. Для индексации требуется доступ к API;
его ошибки сохраняются без текста запроса и ключа. Генерация ответов здесь не вызывается.

Для общей с backend базы задайте `QDRANT_URL`, `QDRANT_API_KEY` и
`QDRANT_COLLECTION`. Пустой URL включает встроенный persistent Qdrant в
`data/qdrant`: это локальный режим для одного процесса. Сервер Qdrant здесь
автоматически не создаётся; используйте сервис партнёра. Коллекция единая для
всех источников. Смена модели или размерности требует новой
коллекции и `reindex-all`; несовместимые коллекции не перезаписываются.

## Сайт

```bash
python -m ingestion.cli crawl-kbtu --dry-run --max-pages 10 --depth 2
python -m ingestion.cli crawl-kbtu
```

`crawl` — псевдоним `crawl-kbtu`. Dry-run читает HTML для обнаружения ссылок,
но не скачивает PDF/DOCX, не создаёт реестр, файлы или индекс. Сканируются
`kbtu.edu.kz/ru/studentam/*` и документы `.pdf/.doc/.docx`, найденные по ссылкам
с этих страниц. Разрешён также точный host `www.kbtu.edu.kz`. Внешние домены,
другие HTML-разделы и redirect за границы scope блокируются до запроса.

Scrapy учитывает robots.txt, использует задержку не меньше секунды, до двух
запросов на домен, AutoThrottle, ограничение глубины/числа URL и повторы с
экспоненциальной задержкой. Оригинальный и конечный URL, HTTP status и время
скачивания записываются в manifest. `.doc` сохраняется в raw с понятным статусом
ошибки: для индексации его нужно конвертировать в DOCX, например LibreOffice.

## Локальные документы и Telegram

Для вашей части подготовки данных, пока партнёр разрабатывает backend, API-ключ
и Qdrant не обязательны:

```bash
python -m ingestion.cli crawl-kbtu --parse-only
python -m ingestion.cli ingest-folder data/inbox/telegram --parse-only
```

Оригиналы, parsed JSON, chunks и реестр сохраняются; документ имеет `pending`
(подготовлен, ожидает индексации). Повторный запуск не создаёт дубли. Когда ключ
и общий Qdrant настроены, выполните `reindex-all`. `verify` до индексации сообщает
о pending-документах, поскольку проверяет готовность именно индекса.

После изменения парсера подготовленные, ещё не опубликованные документы можно
обновить командой `python scripts/reparse_pending.py`. Оригиналы остаются на месте.

Положите скачанные файлы в `data/inbox/telegram` или `data/inbox/manual`:

```bash
python -m ingestion.cli ingest-folder data/inbox/telegram
python -m ingestion.cli ingest-file "path/to/Academic Policy.pdf"
python -m ingestion.cli ingest-file "path/to/file.docx" --source-channel telegram
```

Поддерживаются PDF, DOCX, HTML, UTF-8 TXT/Markdown/CSV и XLSX; бинарные форматы
проверяются по содержимому, текстовые — также по расширению. Файлы в inbox
не перемещаются. Успех отмечается в `data/processed`, каждый запуск повторно
проверяет хеш, поэтому изменение файла обнаруживается. Повторный импорт одинаковых
байтов или нормализованного текста не создаёт повторных chunks. Дополнительные
источники такого документа сохраняются в `document_sources`.

Все локальные источники, включая `internal_kbtu`, изначально `unverified`.
Локальный CLI предназначен для оператора базы знаний, доступ ограничивается
правами ОС. Повысить доверие после проверки происхождения:

```bash
python -m ingestion.cli set-trust DOC_ID official --reason "Проверен оригинал КБТУ"
python -m ingestion.cli set-trust DOC_ID verified_internal --reason "Подтверждён отделом"
```

Это обновляет реестр и payload Qdrant без парсинга и пересчёта embeddings.
Telegram-бот не создаётся: партнёр может передавать файлы в inbox после своей
проверки admin ID. Токен бота модулю не нужен.

## Метаданные и версии

Название, номер, год, язык, аудитория и категории извлекаются локальными
правилами. Неизвестные поля остаются null. Для неоднозначных документов при первом
импорте задайте JSON через `--metadata metadata.json`, например:

```json
{
  "logical_document_key": "academic-policy:ru",
  "document_number": "51-2-25",
  "academic_year": "2026-2027",
  "version": "2026",
  "effective_from": "2026-09-01",
  "target_audience": "bachelor"
}
```

Доверие нельзя повысить metadata-файлом. Для объединения редакций используется
нормализованное название без года/номера версии и язык. Категория сама по себе
не объединяет документы. Для переименованных регламентов используйте явный
`logical_document_key`. Автоматическое определение семейств — эвристика, которую
нужно проверять оператору. Номера версий и явные даты важнее времени загрузки.

Внутри семейства выбирается одна действующая версия с учётом дат и уровня доверия:
`official > verified_internal > unverified`. Неподтверждённый документ не вытесняет
официальный; будущее вступление в силу не активируется заранее. Старые файлы и
chunks сохраняются, меняется только `is_current`; записывается `supersedes_doc_id`.
Полностью истёкшее семейство может не иметь current-версии.

```bash
python -m ingestion.cli refresh-current
```

Запускайте эту команду ежедневно для активации/истечения документов по датам.

## Форматы, OCR и chunking

- HTML: Trafilatura + BeautifulSoup, удаление меню, cookies, footer;
  заголовки, списки и таблицы сохраняются структурно.
- PDF: PyMuPDF, отдельные страницы с номерами, эвристика заголовков и таблицы.
  OCR не запускается для обычного текстового слоя.
- DOCX: python-docx, порядок абзацев и таблиц, заголовки и списки.

Сканированный/частично сканированный PDF получает `needs_ocr` и не публикуется
частично в индекс. Для повторного импорта выполните
`python scripts/setup_ocr.py --enable`: языковые данные `rus+kaz+eng` будут скачаны
из официального `tesseract-ocr/tessdata_fast`, а `OCR_ENABLED=true` и `OCR_TESSDATA`
записаны в корневой `.env`. После перезапуска backend нажмите «Обновить базу».
OCR работает через встроенный движок PyMuPDF; отдельный `tesseract.exe` не требуется.
Можно также задать уже установленный каталог через `OCR_TESSDATA` или `TESSDATA_PREFIX`.
Пустой PDF также не индексируется. OCR, сложные многоколоночные PDF и качество
таблиц требуют ручной выборочной проверки на ваших документах.

Дочерние chunks строятся внутри раздела/подраздела/страницы из целых блоков;
длинные блоки делятся по токенам с перекрытием. По умолчанию бюджет 700, overlap
100, tokenizer `cl100k_base`. Перед отправкой в API дополнительно проверяется
длина полного входа с контекстом. Маленькие разделы/страницы дают короткие chunks.
Parent-контекст сохраняется в parsed JSON по `parent_chunk_id`.
В длинных таблицах строки сохраняют заголовок таблицы.

## Хранение и восстановление

```text
data/raw/<source_channel>/<binary_sha256>.<ext>  неизменяемые оригиналы
data/parsed/<doc_id>.json                      document + blocks/pages + chunks + parents
data/manifests/<attempt_id>.json               результат каждой попытки
data/processed/<path_hash>.json                отметка о завершении импорта
data/registry.sqlite3                         документы, версии, источники и запуски
data/qdrant/                                  локальный индекс (если URL пустой)
```

Реестр использует SQLite WAL и межпроцессную блокировку писателя. Backend подключён
к этому же реестру через Pipeline, отдельная база документов не создаётся. Для нескольких
серверов понадобится общий реестр/очередь и распределённая блокировка: текущая
версия рассчитана на один ingestion worker с постоянным локальным диском.
Резервируйте весь DATA_DIR и snapshot серверного Qdrant совместно.

В общем интерфейсе действие «Убрать в архив» устанавливает `metadata.archived_at`.
Такой документ не участвует в выборе действующей версии; его оригинал и chunks
сохраняются. Повторная синхронизация inbox не возвращает его в поиск.

SQLite и Qdrant не образуют общей транзакции. Новые chunks сначала `staging`, затем
публикуются как `ready`. Реестр хранит состояние синхронизации. При сбое старые
оригиналы сохраняются; повторный импорт или `reindex` восстанавливает запись.
Читатель обязан использовать фильтр из INTEGRATION.md. При переключении версии
возможен короткий промежуток без current-версии.

```bash
python -m ingestion.cli inspect DOC_ID
python -m ingestion.cli status
python -m ingestion.cli verify
python -m ingestion.cli reindex DOC_ID
python -m ingestion.cli reindex-all
```

`inspect` читает актуальные метаданные из реестра; document-секция parsed JSON
является снимком на момент parsing/reindex. `verify` проверяет хеши оригиналов,
ID chunks, статус payload и выбор current. Код выхода 1 указывает на проблему;
один повреждённый документ не останавливает пакетный импорт. `needs_ocr` также
требует действия оператора и даёт ненулевой код пакетного запуска.

## Автоматическое обновление

```bash
python scripts/refresh.py
```

Команда обновляет сайт, оба inbox, актуальные версии и выполняет verify.
Добавьте её в Планировщик заданий Windows или cron, например ежедневно ночью.
Рабочая папка — корень проекта, интерпретатор — абсолютный путь к `.venv`.
Не запускайте перекрывающиеся задания. Расписание на компьютере автоматически
не устанавливается.

## Проверки

```bash
python -m pytest -q
python -m ruff check .
python -m mypy
python scripts/smoke_ingestion.py
```

Обычные тесты используют сгенерированные PDF/DOCX, HTML fixture, тестовый embedder,
подменённый клиент OpenAI и настоящий локальный Qdrant в памяти. Они не обращаются
к OpenAI, KBTU или production Qdrant. Tokenizer при первом обращении может
скачать словарь; его можно предварительно кэшировать через `TIKTOKEN_CACHE_DIR`.
Smoke-команда требует `OPENAI_API_KEY`, выполняет платный запрос embeddings
для синтетического PDF и использует persistent Qdrant в отдельном
`data/smoke-openai`: PDF → индекс → повторный импорт → verify.

## Обращение с данными

Оригиналы и parsed-тексты могут содержать персональную информацию: ограничьте
доступ к DATA_DIR. Перед embedding и записью текста в Qdrant выполняется базовая
маскировка email, телефонов и явно отмеченных student IDs/ИИН. Это набор правил,
а не полноценный DLP: списки студентов и закрытые персональные документы следует
отсеивать до помещения в inbox. Тексты после этой маскировки отправляются
в OpenAI embeddings API; парсинг оригиналов выполняется локально.
Raw/parsed/manifests, `.env` и ключи исключены из Git.

## Документация используемых библиотек

- [Scrapy middleware и robots.txt](https://docs.scrapy.org/en/latest/topics/downloader-middleware.html)
- [Qdrant named dense/sparse vectors](https://qdrant.tech/documentation/manage-data/vectors/)
- [OpenAI embeddings API](https://developers.openai.com/api/docs/guides/embeddings)
- [Trafilatura extraction](https://trafilatura.readthedocs.io/en/latest/corefunctions.html)
