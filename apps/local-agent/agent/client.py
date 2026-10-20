"""Typed client for the device endpoints of the backend.

Endpoints (identical to the contract used by the web client):

* ``POST   /api/v1/devices/register``                  -> {device_id, api_key, poll_interval_seconds}
* ``POST   /api/v1/devices/{device_id}/heartbeat``      -> {status, capabilities}
* ``GET    /api/v1/devices/tasks/claim``                -> a task object or 204/empty
* ``POST   /api/v1/devices/tasks/{task_id}/report``     -> {status, result, error}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .transport import Response, Transport, TransportError


class BackendError(RuntimeError):
    """The backend answered with an error status."""

    def __init__(self, status: int, message: str, body: str = "") -> None:
        super().__init__(f"{message} (HTTP {status})")
        self.status = status
        self.message = message
        self.body = body


@dataclass
class Registration:
    device_id: str
    api_key: str
    poll_interval_seconds: int

    @classmethod
    def from_payload(cls, payload: Any) -> "Registration":
        if not isinstance(payload, dict):
            raise BackendError(200, "The registration response is malformed")
        device_id = payload.get("device_id") or payload.get("deviceId")
        api_key = payload.get("api_key") or payload.get("apiKey")
        if not device_id or not api_key:
            raise BackendError(200, "The registration response has no device id or api key")
        interval = payload.get("poll_interval_seconds") or payload.get("pollIntervalSeconds") or 15
        return cls(
            device_id=str(device_id),
            api_key=str(api_key),
            poll_interval_seconds=int(interval),
        )


class BackendClient:
    def __init__(
        self,
        transport: Transport,
        device_id: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.transport = transport
        self.device_id = device_id
        self.api_key = api_key

    # -- helpers -------------------------------------------------------
    def _authorized_headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        authenticated: bool = True,
    ) -> Response:
        headers = self._authorized_headers() if authenticated else {}
        response = self.transport.request(method, path, body=body, headers=headers)
        if response.status >= 400:
            message = response.text().strip() or f"{method} {path} failed"
            raise BackendError(response.status, message, response.text())
        return response

    # -- device lifecycle ----------------------------------------------
    def register(
        self,
        *,
        name: str,
        platform: str,
        version: str,
        capabilities: list[str],
    ) -> Registration:
        response = self._request(
            "POST",
            "/api/v1/devices/register",
            {
                "name": name,
                "platform": platform,
                "version": version,
                "capabilities": list(capabilities),
            },
            authenticated=False,
        )
        registration = Registration.from_payload(response.json())
        self.device_id = registration.device_id
        self.api_key = registration.api_key
        return registration

    def heartbeat(
        self,
        *,
        status: str = "ONLINE",
        capabilities: list[str] | None = None,
    ) -> bool:
        if not self.device_id:
            raise BackendError(400, "The agent is not registered")
        payload: dict[str, Any] = {"status": status}
        if capabilities is not None:
            payload["capabilities"] = list(capabilities)
        self._request(
            "POST",
            f"/api/v1/devices/{self.device_id}/heartbeat",
            payload,
        )
        return True

    # -- task queue ----------------------------------------------------
    def claim_task(self) -> dict[str, Any] | None:
        """Returns the claimed task or ``None`` when the queue is idle."""
        response = self._request("GET", "/api/v1/devices/tasks/claim")
        if response.is_empty:
            return None
        payload = response.json()
        if not payload:
            return None
        if not isinstance(payload, dict):
            raise BackendError(200, "The claim response is malformed")
        return payload

    def report_task(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": status,
            "result": result or {},
            "error": error,
        }
        self._request("POST", f"/api/v1/devices/tasks/{task_id}/report", payload)


__all__ = [
    "BackendClient",
    "BackendError",
    "Registration",
    "TransportError",
]
