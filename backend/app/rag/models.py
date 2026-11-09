"""Реестр моделей: LLM (OpenAI или локальные через Ollama) и эмбеддинги (OpenAI или sentence-transformers).

Идентификаторы моделей имеют вид "<provider>:<name>", например:
    openai:gpt-4o-mini, ollama:qwen2.5:1.5b, groq:llama-3.1-8b-instant,
    openai:text-embedding-3-small, local:intfloat/multilingual-e5-small
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
import numpy as np
from openai import OpenAI

from ..config import get_settings
from .llm import embed_texts as openai_embed_texts
from .llm import get_client

log = logging.getLogger("models")


# ---------------------------------------------------------------- LLM
@dataclass
class GenerationStats:
    """Заполняется по ходу генерации: время до первого токена, скорость, число токенов."""

    started: float = field(default_factory=time.perf_counter)
    first_token_s: float | None = None
    total_s: float | None = None
    output_tokens: int | None = None

    @property
    def tokens_per_s(self) -> float | None:
        if not self.output_tokens or not self.total_s or self.first_token_s is None:
            return None
        gen_time = self.total_s - self.first_token_s
        return round(self.output_tokens / gen_time, 1) if gen_time > 0 else None


def default_llm() -> str:
    return f"openai:{get_settings().openai_chat_model}"


def split_model_id(model_id: str | None) -> tuple[str, str]:
    model_id = model_id or default_llm()
    provider, _, name = model_id.partition(":")
    if provider not in {"openai", "ollama", "groq"} or not name:
        raise ValueError(f"Неизвестная модель: {model_id}")
    return provider, name


def stream_chat(
    model_id: str | None,
    messages: list[dict],
    temperature: float = 0.1,
    stats: GenerationStats | None = None,
) -> Iterator[str]:
    provider, name = split_model_id(model_id)
    stats = stats or GenerationStats()
    if provider == "openai":
        stream = _stream_openai(get_client(), name, messages, temperature, stats)
    elif provider == "groq":
        stream = _stream_openai(
            get_groq_client(), name, messages, temperature, stats, _groq_extra(name)
        )
    else:
        stream = _stream_ollama(name, messages, temperature, stats)
    for token in stream:
        if stats.first_token_s is None:
            stats.first_token_s = time.perf_counter() - stats.started
        yield token
    stats.total_s = time.perf_counter() - stats.started


def complete(
    model_id: str | None, messages: list[dict], temperature: float = 0.1
) -> tuple[str, GenerationStats]:
    stats = GenerationStats()
    text = "".join(stream_chat(model_id, messages, temperature, stats))
    return text, stats


def _stream_openai(
    client: OpenAI,
    name: str,
    messages: list[dict],
    temperature: float,
    stats: GenerationStats,
    extra_body: dict | None = None,
) -> Iterator[str]:
    stream = client.chat.completions.create(
        model=name,
        temperature=temperature,
        stream=True,
        stream_options={"include_usage": True},
        messages=messages,
        extra_body=extra_body,
    )
    for event in stream:
        if event.usage:
            stats.output_tokens = event.usage.completion_tokens
        if event.choices and (delta := event.choices[0].delta.content):
            yield delta


class OllamaUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------- Groq (открытые модели в облаке)
GROQ_URL = "https://api.groq.com/openai/v1"


@lru_cache
def get_groq_client() -> OpenAI:
    key = get_settings().groq_api_key.strip()
    if not key:
        raise ValueError(
            "GROQ_API_KEY не задан. Получите бесплатный ключ на console.groq.com и добавьте в .env"
        )
    return OpenAI(api_key=key, base_url=GROQ_URL, timeout=120, max_retries=3)


def _groq_extra(name: str) -> dict | None:
    # Qwen3.x — «думающие» модели: скрываем рассуждения <think>, оставляя только ответ
    return {"reasoning_format": "hidden"} if "qwen3" in name else None


_groq_cache: dict = {"at": 0.0, "models": None}


def groq_installed() -> set[str] | None:
    """Модели, доступные по ключу Groq (кэш 10 минут); None — ключа нет или API недоступен."""
    if not get_settings().groq_api_key.strip():
        return None
    if time.time() - _groq_cache["at"] < 600 and _groq_cache["models"] is not None:
        return _groq_cache["models"]
    try:
        models = {m.id for m in get_groq_client().models.list().data}
    except Exception as e:  # noqa: BLE001
        log.warning("groq models list failed: %s", e)
        models = None
    _groq_cache.update(at=time.time(), models=models)
    return models


def _stream_ollama(
    name: str, messages: list[dict], temperature: float, stats: GenerationStats
) -> Iterator[str]:
    """Нативный API Ollama: в отличие от /v1 позволяет задать размер контекста (num_ctx).

    По умолчанию Ollama обрезает контекст до 2–4K токенов, а RAG-промпт с 5 чанками больше.
    """
    s = get_settings()
    body = {
        "model": name,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature, "num_ctx": s.ollama_num_ctx},
    }
    try:
        with httpx.stream(
            "POST", f"{s.ollama_url}/api/chat", json=body, timeout=httpx.Timeout(300, connect=5)
        ) as r:
            if r.status_code == 404:
                raise OllamaUnavailable(f"Модель {name} не скачана. Выполните: ollama pull {name}")
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise OllamaUnavailable(f"Ollama: {data['error']}")
                if chunk := data.get("message", {}).get("content"):
                    yield chunk
                if data.get("done"):
                    stats.output_tokens = data.get("eval_count")
    except httpx.ConnectError as e:
        raise OllamaUnavailable(
            f"Ollama не запущен ({s.ollama_url}). Запустите приложение Ollama."
        ) from e


_ollama_cache: dict = {"at": 0.0, "models": None}


def ollama_installed() -> set[str] | None:
    """Имена скачанных моделей Ollama или None, если сервер недоступен (кэш 30 с).

    Без кэша каждый GET /api/models ждал таймаут соединения с выключенным Ollama
    (на Windows до 4.5 с: повторные SYN и попытка IPv6 для «localhost»).
    """
    if time.time() - _ollama_cache["at"] < 30:
        return _ollama_cache["models"]
    names: set[str] | None = None
    try:
        r = httpx.get(f"{get_settings().ollama_url}/api/tags", timeout=httpx.Timeout(2, connect=0.5))
        r.raise_for_status()
        names = set()
        for m in r.json().get("models", []):
            names.add(m["name"])
            if m["name"].endswith(":latest"):
                names.add(m["name"].removesuffix(":latest"))
    except httpx.HTTPError:
        names = None
    _ollama_cache.update(at=time.time(), models=names)
    return names


def list_llms() -> list[dict]:
    s = get_settings()
    installed = ollama_installed()
    models = [
        {
            "id": default_llm(),
            "provider": "openai",
            "name": s.openai_chat_model,
            "label": s.openai_chat_model,
            "available": s.has_openai_key,
            "note": None if s.has_openai_key else "нет OPENAI_API_KEY",
        }
    ]
    for name in s.ollama_model_list:
        available = installed is not None and name in installed
        note = None
        if installed is None:
            note = "Ollama не запущен"
        elif not available:
            note = f"ollama pull {name}"
        models.append(
            {
                "id": f"ollama:{name}",
                "provider": "ollama",
                "name": name,
                "label": name,
                "available": available,
                "note": note,
            }
        )
    groq = groq_installed()
    for name in s.groq_model_list:
        available = groq is not None and name in groq
        note = None
        if not s.groq_api_key.strip():
            note = "нет GROQ_API_KEY"
        elif groq is None:
            note = "Groq недоступен"
        elif not available:
            note = "модель снята с Groq"
        models.append(
            {
                "id": f"groq:{name}",
                "provider": "groq",
                "name": name,
                "label": name.split("/")[-1],
                "available": available,
                "note": note,
            }
        )
    return models


# ---------------------------------------------------------------- Embeddings
class LocalEmbedder:
    """sentence-transformers модель на CPU/GPU. Для семейства E5 нужны префиксы query:/passage:."""

    def __init__(self, name: str):
        from sentence_transformers import SentenceTransformer

        self.name = name
        self.model = SentenceTransformer(name)
        self.is_e5 = "e5" in name.lower()
        self.dimensions = self.model.get_sentence_embedding_dimension()
        self.max_seq_length = self.model.max_seq_length
        self._lock = threading.Lock()  # forward-pass torch-модели из разных потоков сериализуем

    def encode(
        self, texts: list[str], kind: str = "query", batch_size: int = 32, progress=None
    ) -> np.ndarray:
        if self.is_e5:
            texts = [f"{'query' if kind == 'query' else 'passage'}: {t}" for t in texts]
        out = []
        with self._lock:
            for i in range(0, len(texts), batch_size):
                out.append(
                    self.model.encode(
                        texts[i : i + batch_size],
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                )
                if progress:
                    progress(min(i + batch_size, len(texts)), len(texts))
        return (
            np.vstack(out).astype(np.float32) if out else np.zeros((0, self.dimensions), np.float32)
        )


@lru_cache(maxsize=4)
def get_local_embedder(name: str) -> LocalEmbedder:
    log.info("loading embedding model %s", name)
    return LocalEmbedder(name)


def local_embeddings_supported() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def embed(model_id: str | None, texts: list[str], kind: str = "query") -> np.ndarray:
    s = get_settings()
    model_id = model_id or f"openai:{s.embedding_model}"
    provider, _, name = model_id.partition(":")
    if provider == "openai":
        vectors = np.array(openai_embed_texts(texts), dtype=np.float32)
        return vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-12)
    if provider == "local":
        if not local_embeddings_supported():
            raise ValueError(
                "Локальные эмбеддинги не установлены: pip install sentence-transformers"
            )
        return get_local_embedder(name).encode(texts, kind)
    raise ValueError(f"Неизвестная модель эмбеддингов: {model_id}")


def list_embedders() -> list[dict]:
    s = get_settings()
    supported = local_embeddings_supported()
    models = [
        {
            "id": f"openai:{s.embedding_model}",
            "provider": "openai",
            "label": s.embedding_model,
            "available": s.has_openai_key,
            "note": None if s.has_openai_key else "нет OPENAI_API_KEY",
        }
    ]
    for name in s.local_embedding_model_list:
        models.append(
            {
                "id": f"local:{name}",
                "provider": "local",
                "label": name.split("/")[-1],
                "available": supported,
                "note": None if supported else "pip install sentence-transformers",
            }
        )
    return models
