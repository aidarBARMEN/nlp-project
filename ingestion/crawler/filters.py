import posixpath
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

HOSTS = {"kbtu.edu.kz", "www.kbtu.edu.kz"}
TRACKING = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "_ga"}
SENSITIVE = {"token", "password", "key", "api_key", "session", "auth", "access_token"}


def canonicalize(url: str, base="https://kbtu.edu.kz") -> str | None:
    try:
        parts = urlsplit(urljoin(base, url))
        if parts.scheme not in {"http", "https"} or parts.hostname not in HOSTS:
            return None
        if parts.username or parts.password or parts.port not in {None, 80, 443}:
            return None
        query = parse_qsl(parts.query, keep_blank_values=True)
        if any(k.lower() in SENSITIVE for k, _ in query):
            return None
        query = [
            (k, v)
            for k, v in query
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING
        ]
        path = quote(posixpath.normpath(unquote(parts.path or "/")), safe="/:@-._~")
        if parts.path.endswith("/") and not path.endswith("/"):
            path += "/"
        return urlunsplit(
            (parts.scheme.lower(), parts.hostname, path, urlencode(sorted(query)), "")
        )
    except ValueError:
        return None


def is_document(url: str) -> bool:
    return urlsplit(url).path.lower().endswith((".pdf", ".doc", ".docx"))


def in_scope(url: str, *, allow_robots=False) -> bool:
    normalized = canonicalize(url)
    if not normalized:
        return False
    path = unquote(urlsplit(normalized).path)
    if allow_robots and path == "/robots.txt":
        return True
    return path == "/ru/studentam" or path.startswith("/ru/studentam/") or is_document(normalized)
