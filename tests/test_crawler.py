import asyncio

import pytest
from scrapy import Request
from scrapy.crawler import Crawler
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, Response
from scrapy.settings import Settings as ScrapySettings

from ingestion.config import Settings
from ingestion.crawler.filters import canonicalize, in_scope
from ingestion.crawler.kbtu_spider import KBTUSpider, crawler_settings
from ingestion.crawler.middleware import (
    BackoffRetryMiddleware,
    RobotsCompressionMiddleware,
    ScopeMiddleware,
    StrictRobotsTxtMiddleware,
)
from ingestion.services.embedder import lexical_vector


def test_url_canonicalization_and_scope():
    assert (
        canonicalize("https://kbtu.edu.kz/ru/studentam/library?utm_source=x&b=2&a=1#top")
        == "https://kbtu.edu.kz/ru/studentam/library?a=1&b=2"
    )
    assert not in_scope("https://evil.com/file.pdf")
    assert not in_scope("https://kbtu.edu.kz.evil.com/file.pdf")
    assert not in_scope("https://kbtu.edu.kz/ru/studentam/../news")
    assert not in_scope("https://kbtu.edu.kz/ru/studentam/%2e%2e/news")
    assert not in_scope("https://kbtu.edu.kz/ru/studentam-extra")
    assert not in_scope("https://user:password@kbtu.edu.kz/file.pdf")
    assert not in_scope("https://kbtu.edu.kz/file.pdf?token=secret")
    assert in_scope("https://kbtu.edu.kz/uploads/policy.PDF")


def test_redirect_guard():
    middleware = ScopeMiddleware()
    with pytest.raises(IgnoreRequest):
        middleware.process_request(Request("https://external.com/file.pdf"))
    with pytest.raises(IgnoreRequest):
        middleware.process_request(Request("https://kbtu.edu.kz/login"))
    middleware.process_request(Request("https://kbtu.edu.kz/robots.txt"))


def test_crawler_is_bounded_and_dry_run():
    spider = KBTUSpider(dry_run=True, max_pages=3, depth=1)
    request = spider.request("https://kbtu.edu.kz/ru/studentam/library")
    response = HtmlResponse(
        request.url,
        request=request,
        encoding="utf-8",
        body=(
            b'<html><a href="/files/policy.pdf">Policy</a>'
            b'<a href="https://evil.com/x.pdf">bad</a>'
            b'<a href="/ru/studentam/dorm">Dorm</a></html>'
        ),
    )
    requests = list(spider.parse(response))
    assert len(requests) == 1
    assert all("evil" not in url for url in spider.discoveries)
    assert spider.request(request.url) is None
    assert spider.request("https://kbtu.edu.kz/ru/studentam/more") is None
    assert spider.request("https://kbtu.edu.kz/ru/studentam/deep", depth=2) is None


def test_crawler_settings():
    settings = crawler_settings(Settings(_env_file=None))
    assert settings["ROBOTSTXT_OBEY"]
    assert settings["DOWNLOAD_DELAY"] >= 1
    assert settings["CONCURRENT_REQUESTS_PER_DOMAIN"] <= 2
    assert settings["AUTOTHROTTLE_ENABLED"]


def test_retries_use_exponential_backoff(monkeypatch):
    waits = []

    async def record(delay):
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record)
    crawler = Crawler(KBTUSpider, ScrapySettings(crawler_settings(Settings(_env_file=None))))
    from scrapy.statscollectors import MemoryStatsCollector

    crawler.stats = MemoryStatsCollector(crawler)
    crawler.spider = KBTUSpider.from_crawler(crawler)
    middleware = BackoffRetryMiddleware.from_crawler(crawler)
    request = Request("https://kbtu.edu.kz/ru/studentam/library")
    response = Response(request.url, status=503, request=request)
    first = asyncio.run(middleware.process_response(request, response))
    asyncio.run(middleware.process_response(first, response))
    assert waits == [2, 4]


def test_lexical_identifiers_preserved():
    indices, values = lexical_vector("GPA FX Retake WSP Uninet Add/Drop 51-2-25")
    assert len(indices) == 7
    assert indices == sorted(indices)
    assert values == [1.0] * 7


def test_robots_rules_and_network_failure_block_requests():
    from scrapy.robotstxt import ProtegoRobotParser
    from scrapy.statscollectors import MemoryStatsCollector

    crawler = Crawler(KBTUSpider, ScrapySettings(crawler_settings(Settings(_env_file=None))))
    crawler.stats = MemoryStatsCollector(crawler)
    crawler.spider = KBTUSpider.from_crawler(crawler)
    middleware = StrictRobotsTxtMiddleware.from_crawler(crawler)
    robot = ProtegoRobotParser.from_crawler(
        crawler, b"User-agent: *\nDisallow: /files/private.pdf\n"
    )
    with pytest.raises(IgnoreRequest, match="Forbidden"):
        middleware.process_request_2(robot, Request("https://kbtu.edu.kz/files/private.pdf"))
    with pytest.raises(IgnoreRequest, match="unavailable"):
        middleware.process_request_2(None, Request("https://kbtu.edu.kz/files/public.pdf"))
    middleware.process_request_2(robot, Request("https://kbtu.edu.kz/files/public.pdf"))


def test_gzipped_robots_without_encoding_header():
    import gzip

    request = Request("https://kbtu.edu.kz/robots.txt")
    rules = b"User-agent: *\nDisallow: /private\n"
    response = Response(request.url, body=gzip.compress(rules))
    assert RobotsCompressionMiddleware().process_response(request, response).body == rules
