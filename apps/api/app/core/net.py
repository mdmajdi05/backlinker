"""Network helpers with SSRF protection.

Every outbound request triggered by user supplied data (imported spreadsheets,
discovered URLs, verification targets) must go through :func:`safe_get` /
:func:`assert_public_url` so a malicious spreadsheet cannot make the backend
probe internal services.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
_USER_AGENT = settings.user_agent


class UnsafeUrlError(ValueError):
    """Raised when a URL points to a blocked destination."""


def validate_http_url(url: str) -> str:
    """Validate that a user supplied URL is a plain http(s) URL.

    Used for every URL that is stored by the user (target websites,
    opportunity pages, import rows).  Credentials in the URL and exotic
    schemes such as ``ftp://`` or ``file://`` are rejected.
    """
    if not url or not isinstance(url, str):
        raise UnsafeUrlError("A URL is required")
    candidate = url.strip()
    if not candidate:
        raise UnsafeUrlError("A URL is required")
    parsed = urllib.parse.urlparse(candidate)
    scheme = (parsed.scheme or "").lower()
    if not scheme:
        raise UnsafeUrlError(f"Unsupported URL: {candidate} (only http and https are allowed)")
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"Unsupported URL scheme '{scheme}'. Only http:// and https:// are allowed."
        )
    if not parsed.hostname:
        raise UnsafeUrlError(f"The URL '{candidate}' does not contain a hostname")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")
    return candidate


def _private_networks_allowed() -> bool:
    return str(getattr(settings, "allow_private_network", "false")).lower() == "true"


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    return not (ip.is_reserved or ip.is_unspecified)


def assert_public_url(url: str) -> str:
    """Validate scheme/host and reject internal destinations."""
    if not url or not isinstance(url, str):
        raise UnsafeUrlError("URL is required")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Unsupported URL scheme: {parsed.scheme or '(missing)'}")
    if not parsed.hostname:
        raise UnsafeUrlError("URL is missing a hostname")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")
    host = parsed.hostname
    if _private_networks_allowed():
        return url.strip()
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Cannot resolve host: {host}") from exc
    for info in infos:
        address = info[4][0]
        if not is_public_ip(address):
            raise UnsafeUrlError(
                f"Destination {host} resolves to a non-public address ({address}) and is blocked"
            )
    return url.strip()


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content: str
    headers: dict[str, str]
    elapsed_ms: int
    redirects: list[str]
    error: str | None = None
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 400


def safe_get(
    url: str,
    *,
    timeout: float | None = None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    max_redirects: int = 5,
    max_bytes: int = 2_000_000,
    allow_robots: bool = False,
    client: httpx.Client | None = None,
) -> FetchResult:
    """Perform an SSRF-checked HTTP request, validating each redirect hop."""
    import time

    request_headers = {"User-Agent": _USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)

    owns_client = client is None
    client = client or httpx.Client(follow_redirects=False, timeout=timeout or settings.http_timeout)
    redirects: list[str] = []
    current = url
    started = time.perf_counter()
    try:
        for _ in range(max_redirects + 1):
            try:
                assert_public_url(current)
            except UnsafeUrlError as exc:
                return FetchResult(
                    url=url,
                    final_url=current,
                    status_code=0,
                    content="",
                    headers={},
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    redirects=redirects,
                    error=str(exc),
                )
            if allow_robots and settings.respect_robots and not _robots_allows(current):
                    return FetchResult(
                        url=url,
                        final_url=current,
                        status_code=0,
                        content="",
                        headers={},
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        redirects=redirects,
                        error=f"Blocked by robots.txt for {current}",
                    )
            try:
                response = client.request(method, current, headers=request_headers)
            except Exception as exc:  # network error
                return FetchResult(
                    url=url,
                    final_url=current,
                    status_code=0,
                    content="",
                    headers={},
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    redirects=redirects,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if response.is_redirect and response.headers.get("location"):
                location = urllib.parse.urljoin(current, response.headers["location"])
                redirects.append(location)
                current = location
                continue
            content = response.text
            truncated = False
            if len(content.encode("utf-8", errors="ignore")) > max_bytes:
                content = content.encode("utf-8", errors="ignore")[:max_bytes].decode("utf-8", errors="ignore")
                truncated = True
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                content=content,
                headers={k.lower(): v for k, v in response.headers.items()},
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                redirects=redirects,
                truncated=truncated,
            )
        return FetchResult(
            url=url,
            final_url=current,
            status_code=0,
            content="",
            headers={},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            redirects=redirects,
            error="Too many redirects",
        )
    finally:
        if owns_client:
            client.close()


_ROBOT_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _robots_allows(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _ROBOT_CACHE.get(origin)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            client = httpx.Client(timeout=8.0, follow_redirects=True)
            resp = client.get(f"{origin}/robots.txt", headers={"User-Agent": _USER_AGENT})
            if resp.status_code == 200 and "html" not in resp.headers.get("content-type", ""):
                rp.parse(resp.text.splitlines())
            else:
                rp = None
            client.close()
        except Exception:
            rp = None
        _ROBOT_CACHE[origin] = rp
    if rp is None:
        return True
    return rp.can_fetch(_USER_AGENT, url)


def extract_links(html: str, base_url: str) -> list[dict[str, Any]]:
    """Parse all anchors from an HTML document.

    Returns dicts with ``href`` (absolute), ``text`` (anchor text) and
    ``rel`` (raw rel attribute).
    """
    from bs4 import BeautifulSoup

    out: list[dict[str, Any]] = []
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        href = href.strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urllib.parse.urljoin(base_url, href)
        out.append(
            {
                "href": absolute,
                "text": (anchor.get_text(" ", strip=True) or "").strip(),
                "rel": (anchor.get("rel") or [] if isinstance(anchor.get("rel"), list) else anchor.get("rel")),
                "title": anchor.get("title"),
            }
        )
    return out


def html_text(html: str, max_chars: int = 20_000) -> str:
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:max_chars]
