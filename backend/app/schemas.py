from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ingestion.models import Trust


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Message] = []
    # id модели из /api/models, например "ollama:qwen2.5:1.5b"; None = OpenAI по умолчанию
    model: str | None = Field(default=None, max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = False


class TokenizeRequest(BaseModel):
    text: str = Field(max_length=20000)
    model: str | None = None


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=8)
    model: str | None = Field(default=None, max_length=200)


class TrustRequest(BaseModel):
    trust_level: Trust
    reason: str = Field(min_length=3, max_length=500)


class EmailReplyRequest(BaseModel):
    sender: str = Field(default="", max_length=500)
    sender_name: str = Field(default="", max_length=200)
    subject: str = Field(default="", max_length=1000)
    # text/plain или HTML письма; цитата предыдущей переписки отрезается на backend
    body: str = Field(default="", max_length=100_000)
    model: str | None = Field(default=None, max_length=100)
    # Message-ID и References входящего письма: черновик попадёт в ту же цепочку
    message_id: str = Field(default="", max_length=1000)
    references: str = Field(default="", max_length=10_000)
    # true = сразу сохранить ответ в «Черновики» ящика EMAIL_OWN_ADDRESS по IMAP
    save_draft: bool = False
    # заголовки письма (ключи в нижнем регистре) — для отсева рассылок; дата получения
    headers: dict[str, str] = Field(default_factory=dict, max_length=200)
    received_at: datetime | None = None


class EvalRunRequest(BaseModel):
    kind: Literal["dataset", "retrieval", "generation"]
    # id моделей; пусто = все доступные
    models: list[str] = []
    # ограничение числа вопросов (для быстрой проверки)
    limit: int | None = Field(default=None, ge=1, le=500)
