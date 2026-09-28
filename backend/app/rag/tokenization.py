"""Токенизация: BPE-токены (tiktoken) для чанкинга/LLM и лексические токены для BM25."""
from __future__ import annotations

import re
from functools import lru_cache

import snowballstemmer
import tiktoken

from ..config import get_settings


@lru_cache
def get_encoding(model: str | None = None) -> tiktoken.Encoding:
    """BPE-токенизатор OpenAI. Для text-embedding-3-* это cl100k_base, для gpt-4o* — o200k_base."""
    model = model or get_settings().openai_embedding_model
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("o200k_base" if "4o" in model or "4.1" in model else "cl100k_base")


def count_tokens(text: str, model: str | None = None) -> int:
    return len(get_encoding(model).encode(text, disallowed_special=()))


# ---------------------------------------------------------------- лексическая токенизация (BM25)
_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_CYRILLIC_RE = re.compile(r"[а-яё]")
_KAZ_LETTERS = set("әғқңөұүһі")

_ru_stemmer = snowballstemmer.stemmer("russian")
_en_stemmer = snowballstemmer.stemmer("english")

STOPWORDS = {
    # ru
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она", "так", "его", "но",
    "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "ли", "если", "уже", "или", "ни", "быть", "был",
    "него", "до", "вас", "нибудь", "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей", "может",
    "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам", "чтоб", "без",
    "будто", "чего", "раз", "тоже", "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому", "этого",
    "какой", "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "были", "куда", "зачем", "всех",
    "можно", "при", "об", "другой", "хоть", "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего",
    "них", "какая", "много", "разве", "эту", "моя", "свою", "этой", "перед", "иногда", "лучше", "чуть", "том",
    "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между", "это", "также", "которые", "который",
    # en
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "are", "be", "for", "with", "as", "by", "at", "it",
    "this", "that", "from", "was", "were", "can", "i", "how", "what", "do", "does", "my",
    # kk
    "және", "мен", "бен", "пен", "де", "та", "те", "бұл", "осы", "үшін", "қалай", "ма", "ме", "ба", "бе",
}


def lexical_tokens(text: str) -> list[str]:
    """Нормализация для BM25: нижний регистр, удаление стоп-слов, стемминг ru/en.

    Казахский стеммер в snowball отсутствует, поэтому казахские слова только нормализуются.
    Аббревиатуры (GPA, ДС, РУП) сохраняются как есть в нижнем регистре.
    """
    tokens = []
    for raw in _WORD_RE.findall(text.lower().replace("ё", "е")):
        if raw in STOPWORDS or (len(raw) == 1 and not raw.isdigit()):
            continue
        if len(raw) <= 4 and raw.isalpha():  # аббревиатуры и короткие слова не стеммим
            tokens.append(raw)
        elif _KAZ_LETTERS & set(raw):
            tokens.append(raw)
        elif _CYRILLIC_RE.search(raw):
            tokens.append(_ru_stemmer.stemWord(raw))
        elif raw.isascii() and raw.isalpha():
            tokens.append(_en_stemmer.stemWord(raw))
        else:
            tokens.append(raw)
    return tokens
