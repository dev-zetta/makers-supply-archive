from __future__ import annotations

import random
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from makers_supply import __version__

USER_AGENT = (
    f"makers-supply-archive/{__version__} "
    "(+https://github.com/dev-zetta/makers-supply-archive)"
)


class RobotsDeniedError(RuntimeError):
    pass


@dataclass
class ArchiveHttpClient:
    delay: float = 2.0
    jitter: float = 1.0
    retries: int = 6
    timeout: float = 30.0
    transport: httpx.BaseTransport | None = None
    _robots: dict[str, RobotFileParser | None] = field(default_factory=dict, init=False)
    _last_request: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=self.timeout,
            transport=self.transport,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        )

    def __enter__(self) -> ArchiveHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.client.close()

    def _origin(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        interval = self.delay
        if self.delay > 0 and self.jitter > 0:
            interval += random.uniform(0, self.jitter)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request[host] = time.monotonic()

    def _robots_parser(self, url: str) -> RobotFileParser | None:
        origin = self._origin(url)
        if origin in self._robots:
            return self._robots[origin]
        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            self._throttle(robots_url)
            response = self.client.get(robots_url)
            if response.is_success:
                parser.parse(response.text.splitlines())
                self._robots[origin] = parser
                return parser
            if 400 <= response.status_code < 500:
                self._robots[origin] = None
                return None
        except httpx.HTTPError as error:
            error_request = getattr(error, "request", None)
            if error_request is not None and self._origin(str(error_request.url)) != origin:
                self._robots[origin] = None
                return None
            parser.parse(["User-agent: *", "Disallow: /"])
        else:
            parser.parse(["User-agent: *", "Disallow: /"])
        self._robots[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parser = self._robots_parser(url)
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
        check_robots: bool = True,
        stream: bool = False,
    ) -> httpx.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDeniedError(f"robots.txt disallows {url}")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._throttle(url)
                if stream:
                    request = self.client.build_request(
                        method, url, headers=headers, json=json
                    )
                    response = self.client.send(request, stream=True)
                else:
                    response = self.client.request(method, url, headers=headers, json=json)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError:
                        response.close()
                        raise
                    return response
                response.close()
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = max(
                            0.0, parsedate_to_datetime(retry_after).timestamp() - time.time()
                        )
                else:
                    wait = min(2**attempt, 30)
                time.sleep(wait)
                last_error = httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 30))
        assert last_error is not None
        raise last_error

    def get(self, url: str, *, check_robots: bool = True) -> httpx.Response:
        return self.request("GET", url, check_robots=check_robots)
