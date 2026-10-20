"""Persistent configuration of the local agent.

The API key is a machine secret - it is stored with 0600 permissions in
``~/.autobacklinker/agent.json``.
"""

from __future__ import annotations

import json
import os
import platform
import stat
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_POLL_INTERVAL = 15
CONFIG_FILE_NAME = "agent.json"


def agent_home() -> Path:
    """The directory that holds the agent configuration and logs."""
    override = os.environ.get("AUTOBL_AGENT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".autobacklinker"


def config_path() -> Path:
    return agent_home() / CONFIG_FILE_NAME


def log_path() -> Path:
    return agent_home() / "logs" / "agent.log"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AgentConfig:
    """Everything the agent needs to talk to the backend."""

    device_id: str
    api_key: str
    server_url: str
    name: str = field(default_factory=lambda: f"{platform.node()}-agent")
    platform: str = field(default_factory=platform.system)
    version: str = "1.0.0"
    capabilities: list[str] = field(default_factory=list)
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL
    registered_at: str = field(default_factory=utc_now)
    last_seen: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentConfig":
        return cls(
            device_id=str(data.get("device_id", "")),
            api_key=str(data.get("api_key", "")),
            server_url=str(data.get("server_url", "")),
            name=str(data.get("name", "agent")),
            platform=str(data.get("platform", platform.system())),
            version=str(data.get("version", "1.0.0")),
            capabilities=list(data.get("capabilities", [])),
            poll_interval_seconds=int(
                data.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL)
            ),
            registered_at=str(data.get("registered_at", utc_now())),
            last_seen=data.get("last_seen"),
        )

    def public_dict(self) -> dict[str, Any]:
        """The configuration without the secret (used for logging)."""
        data = self.to_dict()
        data.pop("api_key", None)
        return data


def ensure_directories() -> None:
    (agent_home() / "logs").mkdir(parents=True, exist_ok=True)


def load_config() -> AgentConfig | None:
    """Reads the stored configuration, ``None`` when the agent is unregistered."""
    path = config_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return AgentConfig.from_dict(data)


def save_config(config: AgentConfig) -> Path:
    """Stores the configuration with 0600 permissions."""
    ensure_directories()
    path = config_path()
    payload = json.dumps(config.to_dict(), indent=2, sort_keys=True)

    # Write atomically so a crash never leaves a half written secret behind.
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=".agent-",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return path


def delete_config() -> None:
    try:
        config_path().unlink()
    except FileNotFoundError:
        pass


def default_capabilities(include_browser: bool) -> list[str]:
    """The capabilities the agent advertises to the backend."""
    capabilities = [
        "submit",
        "verify",
        "http",
        f"python-{platform.python_version()}",
    ]
    if include_browser:
        capabilities.append("browser")
    return capabilities
