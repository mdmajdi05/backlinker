"""Logging setup of the agent.

The agent writes a redacted log file to ``~/.autobacklinker/logs/agent.log``.
Secrets (API keys, bearer tokens, passwords) must never end up in that file.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

from .config import log_path

REDACTED = "***"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1" + REDACTED),
    (re.compile(r"(?i)(\bapi[_-]?key\b\s*[:=]\s*\"?)[^\"',\s}]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(\btoken\b\s*[:=]\s*\"?)[^\"',\s}]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(\bpassword\b\s*[:=]\s*\"?)[^\"',\s}]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(\bauthorization\b\s*[:=]\s*\"?)[^\"',\s}]+"), r"\1" + REDACTED),
    (re.compile(r"\babk_[A-Za-z0-9_\-]{8,}"), REDACTED),
    (re.compile(r"\b[0-9a-fA-F]{40,}\b"), REDACTED),
)


def redact(text: str) -> str:
    """Removes secrets from a log message."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(
    level: str = "INFO",
    file_path: Path | None = None,
    console: bool = True,
) -> logging.Logger:
    """Configures the root logger and returns the agent logger."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.addFilter(RedactingFilter())
        root.addHandler(stream)

    target = file_path or log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)
    except OSError:  # pragma: no cover - read only home
        pass

    logging.getLogger("agent").setLevel(getattr(logging, str(level).upper(), logging.INFO))
    return logging.getLogger("agent")
