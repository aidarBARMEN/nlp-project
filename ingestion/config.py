from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / "backend" / ".env", PROJECT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = PROJECT_DIR / "data"
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "kbtu_knowledge"
    openai_api_key: SecretStr | None = None
    openai_timeout: float = Field(default=60, gt=0)
    openai_max_retries: int = Field(default=3, ge=0, le=10)
    embedding_provider: Literal["openai"] = "openai"
    embedding_model: Literal["text-embedding-3-small", "text-embedding-3-large"] = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL"),
    )
    embedding_dimensions: int | None = Field(default=None, ge=1)
    embedding_batch_size: int = Field(default=8, ge=1, le=256)
    kbtu_crawler_delay: float = Field(default=1, ge=1)
    kbtu_crawler_concurrency: int = Field(default=2, ge=1, le=2)
    kbtu_crawler_depth: int = Field(default=3, ge=1, le=10)
    kbtu_crawler_max_pages: int = Field(default=100, ge=1)
    chunk_tokens: int = Field(default=700, ge=128, le=900)
    chunk_overlap: int = Field(default=100, ge=0)
    max_file_mb: int = Field(default=50, ge=1, le=250)
    ocr_enabled: bool = False
    ocr_languages: str = "rus+kaz+eng"

    @model_validator(mode="after")
    def validate_overlap(self):
        if not self.data_dir.is_absolute():
            self.data_dir = (PROJECT_DIR / self.data_dir).resolve()
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_TOKENS")
        maximum = 1536 if self.embedding_model == "text-embedding-3-small" else 3072
        if self.embedding_dimensions and self.embedding_dimensions > maximum:
            raise ValueError(f"EMBEDDING_DIMENSIONS must not exceed {maximum} for this model")
        return self

    @property
    def dense_dimensions(self) -> int:
        return self.embedding_dimensions or (
            1536 if self.embedding_model == "text-embedding-3-small" else 3072
        )

    @property
    def embedding_signature(self) -> str:
        return (
            f"{self.embedding_provider}:{self.embedding_model}:{self.dense_dimensions}:lexical-v1"
        )
