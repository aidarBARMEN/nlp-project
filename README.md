# KBTU Smart Assistant — подготовка данных

Модуль data engineering: сайт КБТУ и локальные HTML/PDF/DOCX → оригиналы →
структурированный текст → версии → dense/sparse Qdrant.
API, чат-бот, генерация ответов и frontend разрабатываются отдельно.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m ingestion.cli crawl-kbtu --dry-run
python -m ingestion.cli ingest-folder data/inbox/telegram --parse-only
python -m ingestion.cli status
```

`--parse-only` готовит оригиналы, метаданные и chunks без API-ключа и Qdrant.
Для индексации скопируйте `.env.example` в `.env` (PowerShell: `Copy-Item .env.example .env`)
и укажите `OPENAI_API_KEY`. По умолчанию используется OpenAI `text-embedding-3-small`;
тексты после базовой маскировки персональных данных отправляются в embeddings API.
Веса моделей скачивать не нужно. Затем выполните:

```bash
python -m ingestion.cli reindex-all
python -m ingestion.cli verify
```

Инструкция: [docs/INGESTION.md](docs/INGESTION.md).
Контракт для backend партнёра: [docs/INTEGRATION.md](docs/INTEGRATION.md).
Результаты проверок: [docs/VALIDATION.md](docs/VALIDATION.md).
