"""HTTP transport of the agent.

The agent only uses the Python standard library so it can run on a clean
machine. The transport is intentionally small and completely synchronous - the
agent is a single purpose worker.

``MockTransport`` is used by the test suite to verify the exact HTTP calls
without touching the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

DEFAULT_TIMEOUT = 30.0


class TransportError(RuntimeError):
    """Raised when the backend cannot be reached."""


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.status == 204 or not self.body.strip()

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TransportError(f"Invalid JSON response: {error}") from error

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Transport(Protocol):
    """The minimal interface the agent needs from an HTTP client."""

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Response:
        ...


class UrllibTransport:
    """A blocking transport built on :mod:`urllib.request`."""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def url_for(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Response:
        url = self.url_for(path)
        data: bytes | None = None
        request_headers = {"Accept": "application/json", "User-Agent": "AutoBacklinker-Agent/1.0"}

        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        if headers:
            request_headers.update(headers)

        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method.upper()
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                return Response(
                    status=response.status,
                    body=payload,
                    headers={k.lower(): v for k, v in response.headers.items()},
                )
        except urllib.error.HTTPError as error:  # 4xx / 5xx carry a body
            payload = error.read() if hasattr(error, "read") else b""
            return Response(
                status=error.code,
                body=payload,
                headers={k.lower(): v for k, v in (error.headers or {}).items()},
            )
        except urllib.error.URLError as error:
            raise TransportError(f"Cannot reach {url}: {error.reason}") from error
        except (OSError, TimeoutError) as error:
            raise TransportError(f"Cannot reach {url}: {error}") from error


class MockTransport:
    """A transport that replays canned responses (used by the tests)."""

    def __init__(
        self,
        responses: list[Response] | Callable[[str, str, Any], Response],
    ) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Response:
        self.calls.append(
            {
                "method": method.upper(),
                "path": path,
                "body": body,
                "headers": headers or {},
            }
        )
        if callable(self.responses):
            return self.responses(method.upper(), path, body)
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {path}")
        return self.responses.pop(0)


def build_query(params: dict[str, Any] | None) -> str:
    if not params:
        return ""
    query = urllib.parse.urlencode(
        {key: value for key, value in params.items() if value is not None},
        doseq=True,
    )
    return f"?{query}" if query else ""
