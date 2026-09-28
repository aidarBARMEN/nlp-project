import re
from urllib.parse import urljoin, urlsplit

import trafilatura
from bs4 import BeautifulSoup, Tag

from ingestion.models import Block, BlockKind, ParsedDocument
from ingestion.services.normalizer import normalize


def parse_html(data: bytes, source: str) -> ParsedDocument:
    soup = BeautifulSoup(data, "html.parser")
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else "Untitled page"
    links = []
    for a in soup.select("a[href]"):
        url = urljoin(source, str(a["href"]))
        if urlsplit(url).hostname in {"kbtu.edu.kz", "www.kbtu.edu.kz"} and urlsplit(
            url
        ).path.lower().endswith((".pdf", ".doc", ".docx")):
            links.append({"title": a.get_text(" ", strip=True), "url": url})
    for node in soup.select(
        "nav, footer, header, script, style, aside, [role=navigation], "
        ".breadcrumb, .breadcrumbs, .cookie, .cookie-banner, .social, .menu"
    ):
        node.decompose()
    article = soup.find("main") or soup.find("article") or soup.select_one(".item-page")
    # Trafilatura handles generic layouts; explicit article containers preserve heading order.
    extracted = trafilatura.extract(
        str(soup),
        output_format="xml",
        include_tables=True,
        include_links=True,
        include_comments=False,
    )
    if article is None and extracted:
        article = BeautifulSoup(extracted, "xml").find("main")
    if article is None:
        article = soup.body or soup
    assert isinstance(article, Tag)
    blocks: list[Block] = []
    section = subsection = None
    for node in article.find_all(["h1", "h2", "h3", "head", "p", "li", "item", "table", "a"]):
        if node.find_parent(["table", "li", "item"]):
            continue
        text = normalize(node.get_text(" ", strip=True))
        if not text:
            continue
        kind: BlockKind = "paragraph"
        spoiler = re.fullmatch(r"\{spoilers?=([^}]+)\}", text)
        if re.fullmatch(r"\{/spoilers?\}", text):
            continue
        if spoiler:
            text = spoiler[1].strip()
            section, subsection, kind = text, None, "heading"
        elif node.name == "a":
            url = urljoin(source, str(node.get("href", "")))
            if not any(link["url"] == url for link in links):
                continue
            text, kind = f"{text} — {url}", "list"
        elif node.name in {"h1", "h2", "h3", "head"}:
            level = str(node.get("rend", node.name))
            if level in {"h3", "3"}:
                subsection = text
            else:
                section, subsection = text, None
            kind = "heading"
        elif node.name == "table":
            rows = node.find_all(["tr", "row"])
            text = "\n".join(
                " | ".join(
                    c.get_text(" ", strip=True)
                    for c in row.find_all(["th", "td", "cell"], recursive=False)
                )
                for row in rows
            )
            kind = "table"
        elif node.name in {"li", "item"}:
            kind = "list"
        blocks.append(Block(text=text, kind=kind, section=section, subsection=subsection))
    return ParsedDocument(title=title, blocks=blocks, metadata={"document_links": links})
