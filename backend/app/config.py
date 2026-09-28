"""Backend and ingestion share the root .env, DATA_DIR and vector schema."""

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
