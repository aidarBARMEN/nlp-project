"""Backend and ingestion share the root .env, DATA_DIR and vector schema."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ingestion.config import PROJECT_DIR
from ingestion.config import Settings as IngestionSettings

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(IngestionSettings):
    openai_chat_model: str = "gpt-4o-mini"
    documents_dir: Path | None = None
    candidates_k: int = Field(default=20, ge=1, le=100)
    rerank_k: int = Field(default=15, ge=1, le=100)
    final_k: int = Field(default=5, ge=1, le=20)
    reranker: Literal["none", "llm"] = "llm"
    query_rewrite: bool = True
    moderation: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Альтернативные (не OpenAI) модели: локальные LLM через Ollama и эмбеддинги
    # sentence-transformers. Используются в чате (выбор модели) и в оценке качества.
    ollama_url: str = "http://localhost:11434"
    ollama_models: str = "qwen2.5:1.5b,gemma3:1b,llama3.2:1b"
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=131072)
    local_embedding_models: str = (
        "intfloat/multilingual-e5-small,sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    # Открытые LLM в облаке Groq (OpenAI-совместимый API, бесплатный ключ: console.groq.com)
    groq_api_key: str = ""
    # каталог Groq часто меняется: актуальный список — GET https://api.groq.com/openai/v1/models
    groq_models: str = "qwen/qwen3.8-27b"
    # LLM-судья для метрик генерации (faithfulness, relevance, correctness)
    eval_judge_model: str = "gpt-4o-mini"

    # Черновики ответов деканата на письма (n8n -> POST /api/email/reply)
    email_api_token: str = ""
    # Ящик деканата: письма с него не обрабатываются; с ним же черновики пишутся по IMAP
    email_own_address: str = ""
    # Gmail: пароль приложения (myaccount.google.com/apppasswords), не обычный пароль
    email_app_password: str = ""
    email_imap_host: str = "imap.gmail.com"
    email_imap_port: int = 993
    # Письма, полученные раньше этого момента, не обрабатываются (пишет scripts/setup_n8n.py)
    email_start_after: datetime | None = None
    email_signature: str = "С уважением,\nДеканат КБТУ"

    @property
    def ollama_model_list(self) -> list[str]:
        return [m.strip() for m in self.ollama_models.split(",") if m.strip()]

    @property
    def groq_model_list(self) -> list[str]:
        return [m.strip() for m in self.groq_models.split(",") if m.strip()]

    @property
    def local_embedding_model_list(self) -> list[str]:
        return [m.strip() for m in self.local_embedding_models.split(",") if m.strip()]

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval"

    @property
    def documents_path(self) -> Path:
        path = self.documents_dir or self.data_dir / "inbox" / "manual"
        return path if path.is_absolute() else (PROJECT_DIR / path).resolve()

    @property
    def openai_embedding_model(self) -> str:
        return self.embedding_model

    @property
    def chunk_size(self) -> int:
        return self.chunk_tokens

    @property
    def has_openai_key(self) -> bool:
        key = self.openai_api_key.get_secret_value().strip() if self.openai_api_key else ""
        return bool(key) and key != "sk-..."


@lru_cache
def get_settings() -> Settings:
    return Settings()
