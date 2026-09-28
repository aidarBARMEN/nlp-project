import hashlib
import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\n(?=[a-zа-яәіңғүұқөһ])", "", text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(text: str) -> str:
    return sha256(re.sub(r"\s+", " ", normalize(text)).encode("utf-8"))


def redact(text: str) -> str:
    """Baseline local PII suppression; raw originals remain access-controlled by operator."""
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    text = re.sub(
        r"(?i)\b(student\s*id|студенческий\s*(?:номер|id)|иин|iin)\s*[:#№]?\s*[\w-]+",
        r"\1 [ID]",
        text,
    )
    return re.sub(
        r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)",
        lambda m: "[PHONE/ID]" if len(re.sub(r"\D", "", m[0])) >= 10 else m[0],
        text,
    )
