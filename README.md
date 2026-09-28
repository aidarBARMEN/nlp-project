# KBTU Smart Assistant

Общий проект: **React frontend + FastAPI backend + ingestion + Qdrant**.
Embeddings, генерация ответов и реранкинг используют OpenAI API.
Подготовка документов работает без API-ключа.

## Запуск на Windows

Команды выполняются из корня репозитория. Нужны Python 3.11+ и Node.js 22.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[app,dev]"
Copy-Item .env.example .env
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

Если `.env` уже существует, сохраните его и добавьте недостающие параметры из шаблона.
В корневом `.env` укажите `OPENAI_API_KEY`, затем запустите:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Откройте **http://127.0.0.1:8000**. Backend раздаёт собранный frontend и API с одного адреса.
API-документация: http://127.0.0.1:8000/docs. По умолчанию используется локальный Qdrant,
Docker не требуется. Приложение рассчитано на локальную работу оператора: авторизация
пользователей пока не реализована, поэтому сервер запускается на `127.0.0.1`.

Linux/macOS: используйте `.venv/bin/python` и `npm` вместо Windows-команд.

## Наполнение базы

1. Во вкладке «База знаний» загрузите PDF, DOCX, HTML, TXT, Markdown, XLSX или CSV.
2. Без ключа файлы получают статус «Ожидает индексации». После настройки ключа и
   перезапуска сервера нажмите «Обновить базу».
3. Проверьте происхождение документа и нажмите «Подтвердить». Чат ищет только среди
   действующих, проиндексированных официальных документов.
4. Задайте вопрос в чате: ответ содержит ссылки на источники и страницы PDF.

Текст перед embeddings проходит базовую маскировку email, телефонов и student IDs.
Оригиналы, parsed JSON, история версий и реестр сохраняются в `data/`.
«Убрать в архив» исключает документ из поиска, сохраняя оригинал.
«Переиндексировать» пересчитывает embeddings через API и не удаляет коллекцию.
Обновление inbox не удаляет документы, ранее полученные crawler или через CLI.

Для официальных страниц КБТУ остановите backend, затем выполните:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli crawl-kbtu --parse-only
```

После перезапуска страницы появятся в «Базе знаний»; «Обновить базу» проиндексирует их.
Crawler ограничен студенческими разделами КБТУ и учитывает robots.txt.

### PDF-сканы и OCR

Если PDF состоит из изображений, один раз настройте распознавание:

```powershell
.\.venv\Scripts\python.exe scripts/setup_ocr.py --enable
```

Команда скачивает языковые данные Tesseract для русского, казахского и английского
в `data/tessdata` и включает OCR в `.env`, сохраняя остальные настройки.
После перезапуска backend нажмите «Обновить базу»: сохранённые сканы будут обработаны
повторно, загружать их заново не требуется. Распознавание выполняется локально;
embeddings и ответы по-прежнему создаются через OpenAI.

## Общие настройки

Корневой `.env` используется и ingestion, и backend; пути не зависят от рабочей папки.
Старый `backend/.env` читается как fallback, корневой файл имеет приоритет.

- `OPENAI_API_KEY` — ключ; `OPENAI_CHAT_MODEL` — модель ответов.
- `EMBEDDING_MODEL=text-embedding-3-small`, `EMBEDDING_DIMENSIONS` — необязательная размерность.
- `DATA_DIR=./data`, `QDRANT_COLLECTION=kbtu_knowledge` — общее хранилище.
- `QDRANT_URL` и `QDRANT_API_KEY` — для серверного Qdrant.

В embedded-режиме Qdrant доступен одному процессу: используйте загрузку через интерфейс
или остановите backend перед CLI-индексацией. Для одновременной работы crawler и backend
подключите серверный Qdrant, оставив общий DATA_DIR.

Старую коллекцию backend `kbtu_docs` приложение не перезаписывает. Для переноса оставьте
новое имя `kbtu_knowledge` и нажмите «Обновить базу»: файлы из `backend/data/documents`
тоже импортируются. Новые локальные источники требуют подтверждения.

## Разработка и проверки

Для frontend с горячей перезагрузкой: `npm.cmd --prefix frontend run dev`.
Он открывается на http://localhost:5173 и проксирует API на backend :8000.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
npm.cmd --prefix frontend run build
```

Тесты используют настоящую локальную Qdrant и подменяют OpenAI; платных запросов нет.
Для отдельной проверки реального embeddings API с настроенным ключом:
`python scripts/smoke_ingestion.py`.

Подробнее: [ingestion](docs/INGESTION.md), [интеграция](docs/INTEGRATION.md),
[проверки](docs/VALIDATION.md).
