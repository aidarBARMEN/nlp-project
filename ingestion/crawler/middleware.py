import asyncio
import gzip
from io import BytesIO
from urllib.parse import urlsplit

from scrapy import Request
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
from scrapy.exceptions import IgnoreRequest

from ingestion.crawler.filters import in_scope


class StrictRobotsTxtMiddleware(RobotsTxtMiddleware):
    def process_request_2(self, rp, request):
        if rp is None:
            raise IgnoreRequest("robots.txt unavailable; crawl paused for this host")
        return super().process_request_2(rp, request)

    async def _parse_robots(self, response, netloc, request):
        if response.status >= 400 and response.status not in {404, 410}:
            raise IgnoreRequest("robots.txt returned an error")
        if response.status == 200 and b"<html" in response.body[:1024].lower():
            raise IgnoreRequest("robots.txt returned HTML instead of rules")
        await super()._parse_robots(response, netloc, request)


class ScopeMiddleware:
    def process_request(self, request):
        # Executed for redirect targets too, before any network request.
        if not in_scope(request.url, allow_robots=True):
            raise IgnoreRequest("Request outside public KBTU student scope")


class RobotsCompressionMiddleware:
    def process_response(self, request, response):
        # Some servers return gzipped robots.txt without a Content-Encoding header.
        if urlsplit(response.url).path == "/robots.txt" and response.body.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=BytesIO(response.body)) as stream:
                body = stream.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise IgnoreRequest("robots.txt exceeds decoded size limit")
            return response.replace(body=body)
        return response


class BackoffRetryMiddleware:
    def __init__(self, crawler):
        self.retry = RetryMiddleware.from_crawler(crawler)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    async def process_response(self, request, response):
        result = self.retry.process_response(request, response)
        if isinstance(result, Request):
            delay = min(60, 2 ** result.meta.get("retry_times", 1))
            retry_after = response.headers.get("Retry-After", b"").decode("ascii", errors="ignore")
            if retry_after.isdigit():
                delay = max(delay, min(120, int(retry_after)))
            await asyncio.sleep(delay)
        return result

    async def process_exception(self, request, exception):
        result = self.retry.process_exception(request, exception)
        if isinstance(result, Request):
            await asyncio.sleep(min(60, 2 ** result.meta.get("retry_times", 1)))
        return result
