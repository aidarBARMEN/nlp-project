from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Message] = []


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = False


class TokenizeRequest(BaseModel):
    text: str = Field(max_length=20000)
    model: str | None = None


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=8)
