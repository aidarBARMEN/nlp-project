from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    qdrant_url: str = ""
    qdrant_path: str = "./data/qdrant"
    qdrant_collection: str = "kbtu_docs"

    documents_dir: str = "./data/documents"

    chunk_size: int = 600
    chunk_overlap: int = 120

    candidates_k: int = 20
    rerank_k: int = 15
    final_k: int = 5
    reranker: str = "llm"
    query_rewrite: bool = True
    moderation: bool = False

    cors_origins: str = "http://localhost:5173"

    def resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def documents_path(self) -> Path:
        return self.resolve(self.documents_dir)

    @property
    def qdrant_local_path(self) -> Path:
        return self.resolve(self.qdrant_path)

    @property
    def has_openai_key(self) -> bool:
        key = self.openai_api_key.strip()
        return bool(key) and key != "sk-..."


@lru_cache
def get_settings() -> Settings:
    return Settings()
