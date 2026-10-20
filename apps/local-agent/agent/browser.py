"""Playwright integration.

The agent only uses a browser when a task really needs one (browser form
submissions). If Playwright or its browsers are missing the agent must not
fail silently - it reports the task as "manual intervention required" so a
human can finish the job.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess

BROWSER_MISSING_MESSAGE = (
    "browser runtime not installed - install Playwright with "
    "`pip install playwright` and download the browsers with "
    "`python -m playwright install chromium`"
)


def playwright_installed() -> bool:
    """True when the Playwright Python package can be imported."""
    try:
        return importlib.util.find_spec("playwright") is not None
    except (ImportError, ValueError):
        return False


def browsers_installed() -> bool:
    """True when at least one Playwright browser is present."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override and os.path.isdir(override):
        return True

    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not cache:
        if os.name == "nt":
            local = os.environ.get("LOCALAPPDATA", "")
            cache = os.path.join(local, "ms-playwright") if local else ""
        else:
            home = os.path.expanduser("~")
            cache = os.path.join(home, ".cache", "ms-playwright")
    if cache and os.path.isdir(cache) and os.listdir(cache):
        return True

    # Fall back to the Playwright CLI (it knows the real download location).
    executable = shutil.which("playwright")
    if executable:
        try:
            completed = subprocess.run(
                [executable, "install", "--dry-run", "chromium"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            return "Install location" in (completed.stdout or "")
        except (OSError, subprocess.SubprocessError):
            return False
    return False


def browser_runtime_available() -> bool:
    return playwright_installed() and browsers_installed()


def browser_runtime_status() -> tuple[bool, str]:
    """Returns ``(available, message)`` for the local browser runtime."""
    if not playwright_installed():
        return False, BROWSER_MISSING_MESSAGE
    if not browsers_installed():
        return (
            False,
            "browser runtime not installed - the Playwright package is present "
            "but no browser was downloaded (`python -m playwright install chromium`)",
        )
    return True, "playwright browser runtime available"


__all__ = [
    "BROWSER_MISSING_MESSAGE",
    "browser_runtime_available",
    "browser_runtime_status",
    "browsers_installed",
    "playwright_installed",
]
