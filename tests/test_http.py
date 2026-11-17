import httpx
import pytest

from makersfridge.http import ArchiveHttpClient


def test_robots_rules_are_enforced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, text="ok")

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        assert client.allowed("https://example.com/public")
        assert not client.allowed("https://example.com/private/file.zip")


def test_missing_robots_file_allows_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(403, text="AccessDenied")
        return httpx.Response(200, text="ok")

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        assert client.allowed("https://cdn.example.com/public-file.zip")


def test_unreachable_robots_file_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        assert not client.allowed("https://example.com/public")


def test_broken_cross_origin_robots_redirect_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bad.invalid":
            raise httpx.ConnectError("unresolvable redirect", request=request)
        if request.url.path == "/robots.txt":
            return httpx.Response(302, headers={"Location": "https://bad.invalid/robots.txt"})
        return httpx.Response(200, text="ok")

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        assert client.allowed("https://example.com/public")


def test_throttle_adds_bounded_random_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    moments = iter([11.0, 12.5])
    sleeps: list[float] = []
    monkeypatch.setattr("makersfridge.http.time.monotonic", lambda: next(moments))
    monkeypatch.setattr("makersfridge.http.time.sleep", sleeps.append)
    monkeypatch.setattr("makersfridge.http.random.uniform", lambda _start, _end: 0.5)
    client = ArchiveHttpClient(delay=2.0, jitter=1.0)
    client._last_request["example.com"] = 10.0
    try:
        client._throttle("https://example.com/file.zip")
    finally:
        client.close()

    assert sleeps == [1.5]
    assert client._last_request["example.com"] == 12.5


@pytest.mark.parametrize("rule", ["Crawl-delay: 60", "Request-rate: 1/60"])
def test_supplier_crawl_limits_override_default_delay(
    monkeypatch: pytest.MonkeyPatch,
    rule: str,
) -> None:
    from urllib.robotparser import RobotFileParser

    parser = RobotFileParser()
    parser.parse(["User-agent: *", rule])
    sleeps: list[float] = []
    moments = iter([20.0, 70.0])
    monkeypatch.setattr("makersfridge.http.time.monotonic", lambda: next(moments))
    monkeypatch.setattr("makersfridge.http.time.sleep", sleeps.append)
    with ArchiveHttpClient(delay=2, jitter=0) as client:
        client._robots["https://example.com"] = parser
        client._last_request["example.com"] = 10.0
        client._throttle("https://example.com/product")
    assert sleeps == [50.0]
