import logging
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.http import HtmlResponse

from ingestion.config import Settings
from ingestion.crawler.filters import canonicalize, in_scope, is_document
from ingestion.logging import event
from ingestion.models import IngestResult, utcnow

SEEDS = [
    "https://kbtu.edu.kz/ru/studentam/" + path
    for path in (
        "dokumenty-dlya-obuchayushchikhsya",
        "resursy-dlya-obuchayushchikhsya",
        "obshchezhitie",
        "library",
        "student-life-ru",
    )
]


class KBTUSpider(scrapy.Spider):
    name = "kbtu_students"
    allowed_domains = ["kbtu.edu.kz", "www.kbtu.edu.kz"]

    def __init__(
        self,
        *,
        pipeline=None,
        dry_run=False,
        max_pages=100,
        depth=3,
        outcomes=None,
        discoveries=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.pipeline = pipeline
        self.dry_run = dry_run
        self.max_pages = max_pages
        self.max_depth = depth
        self.seen: set[str] = set()
        self.outcomes = outcomes if outcomes is not None else []
        self.discoveries = discoveries if discoveries is not None else []

    def request(self, url, depth=0):
        url = canonicalize(url)
        if not url or not in_scope(url) or url in self.seen or depth > self.max_depth:
            return None
        if len(self.seen) >= self.max_pages:
            return None
        self.seen.add(url)
        self.discoveries.append(url)
        if self.dry_run and is_document(url):
            event("SOURCE_DISCOVERED", source_url=url, dry_run=True)
            return None
        return scrapy.Request(
            url,
            callback=self.parse,
            errback=self.failed,
            meta={"source_depth": depth, "original_url": url},
        )

    async def start(self):
        for url in SEEDS:
            request = self.request(url)
            if request:
                yield request

    def parse(self, response):
        if not in_scope(response.url):
            return
        final_url = canonicalize(response.url)
        if final_url:
            self.seen.add(final_url)
        provenance = {
            "original_url": response.meta["original_url"],
            "final_url": response.url,
            "http_status": response.status,
            "fetched_at": utcnow().isoformat(),
        }
        event("DOCUMENT_DOWNLOADED", source_url=response.url, http_status=response.status)
        if not self.dry_run and self.pipeline:
            filename = unquote(PurePosixPath(urlsplit(response.url).path).name) or "index.html"
            if isinstance(response, HtmlResponse) and not filename.endswith((".html", ".htm")):
                filename += ".html"
            result = self.pipeline.ingest_bytes(
                response.body,
                filename=filename,
                source=response.url,
                channel="kbtu_website",
                source_url=canonicalize(response.url),
                provenance=provenance,
            )
            self.outcomes.append(result)
        if isinstance(response, HtmlResponse):
            links = {
                canonicalize(href, response.url) for href in response.css("a::attr(href)").getall()
            }
            for url in sorted((u for u in links if u), key=lambda u: (not is_document(u), u)):
                request = self.request(url, response.meta.get("source_depth", 0) + 1)
                if request:
                    yield request

    def failed(self, failure):
        response = getattr(failure.value, "response", None)
        error = type(failure.value).__name__
        status = response.status if response is not None else None
        event("INGEST_FAILED", source_url=failure.request.url, http_status=status, error_type=error)
        result = IngestResult(
            source=failure.request.url, status="failed", error=f"{error}; HTTP {status}"
        )
        self.outcomes.append(result)
        if self.pipeline:
            from uuid import uuid4

            from ingestion.storage import write_json

            write_json(
                self.pipeline.data / "manifests" / f"{uuid4()}.json",
                {
                    **result.model_dump(),
                    "http_status": status,
                    "original_url": failure.request.meta.get("original_url"),
                    "final_url": failure.request.url,
                    "fetched_at": utcnow().isoformat(),
                },
            )


def crawler_settings(settings: Settings) -> dict:
    return {
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": "KBTU-Smart-Assistant-Research-Crawler/1.0",
        "DOWNLOAD_DELAY": settings.kbtu_crawler_delay,
        "DOWNLOAD_DELAY_JITTER": 0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": settings.kbtu_crawler_concurrency,
        "CONCURRENT_REQUESTS": settings.kbtu_crawler_concurrency,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": settings.kbtu_crawler_delay,
        "DEPTH_LIMIT": settings.kbtu_crawler_depth,
        "DOWNLOAD_MAXSIZE": settings.max_file_mb * 1024 * 1024,
        "DOWNLOAD_TIMEOUT": 40,
        "RETRY_TIMES": 3,
        "COOKIES_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
        "EXTENSIONS": {"scrapy.extensions.remote_control.RemoteControl": None},
        "LOG_LEVEL": "WARNING",
        "LOG_INSTALL_ROOT_HANDLER": False,
        "LOG_FORMAT": "%(message)s",
        "DOWNLOADER_MIDDLEWARES": {
            "ingestion.crawler.middleware.ScopeMiddleware": 40,
            "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
            "ingestion.crawler.middleware.StrictRobotsTxtMiddleware": 100,
            "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
            "ingestion.crawler.middleware.BackoffRetryMiddleware": 550,
            "ingestion.crawler.middleware.RobotsCompressionMiddleware": 580,
        },
    }


def crawl(settings: Settings, *, dry_run=False, pipeline=None):
    outcomes: list[IngestResult] = []
    discoveries: list[str] = []
    process = CrawlerProcess(crawler_settings(settings))
    for name in ("scrapy", "twisted", "charset_normalizer", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    crawler = process.create_crawler(KBTUSpider)
    errors = []
    deferred = process.crawl(
        crawler,
        pipeline=pipeline,
        dry_run=dry_run,
        max_pages=settings.kbtu_crawler_max_pages,
        depth=settings.kbtu_crawler_depth,
        outcomes=outcomes,
        discoveries=discoveries,
    )
    deferred.addErrback(lambda failure: errors.append(type(failure.value).__name__))
    process.start()
    if errors:
        raise RuntimeError("Crawler startup failed: " + ", ".join(errors))
    stats = crawler.stats.get_stats()
    if stats.get("spider_exceptions/count", 0):
        raise RuntimeError("Crawler callback failed; inspect structured logs")
    return {
        "dry_run": dry_run,
        "discovered": discoveries,
        "results": [r.model_dump() for r in outcomes],
        "responses": stats.get("response_received_count", 0),
    }, outcomes
