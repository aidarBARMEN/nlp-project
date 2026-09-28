"""Структурный чанкинг: блоки группируются по разделам и режутся по токенам с перекрытием."""
from __future__ import annotations

from dataclasses import dataclass, field

from .parsing import Block
from .tokenization import get_encoding


@dataclass
class Chunk:
    text: str
    section: str | None
    page_start: int | None
    page_end: int | None
    token_count: int
    index: int = 0
    meta: dict = field(default_factory=dict)


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """Режет слишком длинный блок окнами по токенам."""
    enc = get_encoding()
    ids = enc.encode(text)
    if len(ids) <= size:
        return [text]
    step = max(size - overlap, 1)
    return [enc.decode(ids[i : i + size]) for i in range(0, len(ids), step) if ids[i : i + size]]


def chunk_blocks(blocks: list[Block], chunk_size: int, overlap: int) -> list[Chunk]:
    enc = get_encoding()
    chunks: list[Chunk] = []

    # 1. группируем подряд идущие блоки одного раздела
    groups: list[list[Block]] = []
    for b in blocks:
        if b.is_heading or not groups or groups[-1][0].section != b.section:
            groups.append([b])
        else:
            groups[-1].append(b)

    # 2. внутри раздела набираем абзацы до chunk_size, перенося хвост (overlap) в следующий чанк
    for group in groups:
        section = group[0].section
        pieces: list[tuple[str, int | None]] = []
        for b in group:
            if b.is_heading:
                continue  # заголовок уходит в метаданные section и в контекстный префикс эмбеддинга
            for part in _split_long(b.text, chunk_size, overlap):
                pieces.append((part, b.page))

        buf: list[tuple[str, int | None, int]] = []
        buf_tokens = 0
        has_new = False  # есть ли в буфере что-то кроме overlap-хвоста прошлого чанка

        def flush(current_section=section):
            nonlocal buf, buf_tokens, has_new
            has_new = False
            text = "\n\n".join(t for t, _, _ in buf)
            pages = [p for _, p, _ in buf if p is not None]
            chunks.append(Chunk(text, current_section, min(pages, default=None), max(pages, default=None), len(enc.encode(text))))
            # overlap: оставляем последние абзацы суммарно ≤ overlap токенов
            tail, tail_tokens = [], 0
            for item in reversed(buf):
                if tail_tokens + item[2] > overlap:
                    break
                tail.insert(0, item)
                tail_tokens += item[2]
            buf, buf_tokens = (tail, tail_tokens) if tail and len(tail) < len(buf) else ([], 0)

        for text, page in pieces:
            n = len(enc.encode(text))
            if has_new and buf_tokens + n > chunk_size:
                flush()
            while buf and buf_tokens + n > chunk_size:  # хвост не помещается вместе с новым абзацем
                buf_tokens -= buf.pop(0)[2]
            buf.append((text, page, n))
            buf_tokens += n
            has_new = True
        if has_new:
            flush()

    for i, c in enumerate(chunks):
        c.index = i
    return chunks
