"""Isolated browser runtime management.

The browser automation of this platform is **completely isolated** from the
browser a person uses day to day:

* Playwright always launches its own Chromium with a **throw away profile**
  that lives inside the application data directory - the personal Chrome,
  Edge, Firefox or Safari profile of the user is never opened, read or
  controlled.
* No extension is started, no synchronisation service is contacted and no
  credential of the personal browser is reachable.
* The browser runs headless by default.  A headed mode exists for workflows
  that genuinely need a human, and it uses the same isolated profile.
* The runtime (Chromium) is downloaded on demand into a directory that this
  application owns, so several installations never fight over the same
  browser build.

The module is also the single place that knows how the runtime is installed,
where it lives and how to report its state to the user interface.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: Two login windows may ask for the runtime at the same time; installing it
#: twice would fight over the same target directory.
_INSTALL_LOCK = threading.Lock()

#: Arguments that keep the automation browser away from the user's browser.
ISOLATION_ARGS: tuple[str, ...] = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-extensions",
    "--disable-features=Translate,MediaRouter,OptimizationHints,DialMediaRouteProvider",
    "--disable-sync",
    "--disable-service-autorun",
    "--disable-session-crashed-bubble",
    "--disable-popup-blocking",
    "--no-service-autorun",
    "--password-store=basic",
    "--use-mock-keychain",
    "--safebrowsing-disable-auto-update",
    "--metrics-recording-only",
    "--no-pings",
)

#: Environment variables that are removed before the browser is started.
BLOCKED_ENV_PREFIXES = ("CHROME_", "GOOGLE_CHROME", "BROWSER_")


@dataclass
class BrowserRuntimeStatus:
    """What the user interface shows about the browser runtime."""

    available: bool
    headless: bool
    browser_path: str | None = None
    browsers_dir: str | None = None
    profile_dir: str | None = None
    version: str | None = None
    detail: str = ""
    isolation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "headless": self.headless,
            "browser_path": self.browser_path,
            "browsers_dir": self.browsers_dir,
            "profile_dir": self.profile_dir,
            "version": self.version,
            "detail": self.detail,
            "isolation": self.isolation,
        }


def browsers_dir() -> Path:
    """The directory that holds the browser build of this installation."""
    path = settings.data_dir / "browsers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir() -> Path:
    """The throw away profile of the automation browser.

    It is created inside the application data directory, never inside the
    personal browser profile of the user.
    """
    path = settings.data_dir / "browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def playwright_browsers_path() -> str:
    return str(browsers_dir())


def isolation_summary() -> dict[str, Any]:
    """The isolation guarantees - shown in the user interface."""
    return {
        "personal_profile_used": False,
        "own_profile_directory": True,
        "headless_by_default": True,
        "extensions_disabled": True,
        "synchronisation_disabled": True,
        "arguments": list(ISOLATION_ARGS),
        "note": (
            "The automation browser is a separate Chromium instance with its own throw away "
            "profile. The personal Chrome / Edge / Safari profile of this machine is never "
            "opened or controlled."
        ),
    }


#: The names Playwright uses for the browser build, per platform.
_EXECUTABLE_NAMES = (
    "Google Chrome for Testing",  # macOS
    "Chromium",  # older macOS builds
    "chrome",  # Linux
    "chrome.exe",  # Windows
    "chrome-headless-shell",  # the headless only build
    "headless_shell",
)

#: The full browser is preferred over the headless only build.
_EXECUTABLE_RANK = {
    "Google Chrome for Testing": 0,
    "Chromium": 1,
    "chrome": 2,
    "chrome.exe": 2,
    "chrome-headless-shell": 3,
    "headless_shell": 3,
}


def _find_browser_executable() -> Path | None:
    """Locate the downloaded browser build.

    The layout depends on the platform and on the Playwright version, so the
    directory is searched for the known executable names instead of relying on
    one fixed path.
    """
    roots = [browsers_dir(), Path.home() / "Library" / "Caches" / "ms-playwright"]
    for root in roots:
        if not root.exists():
            continue
        candidates = [
            path for path in root.rglob("*") if path.is_file() and path.name in _EXECUTABLE_NAMES
        ]
        if candidates:
            candidates.sort(key=lambda path: (_EXECUTABLE_RANK.get(path.name, 9), len(path.parts)))
            return candidates[0]
    return None


def runtime_status() -> BrowserRuntimeStatus:
    """Report whether the browser runtime is ready."""
    executable = _find_browser_executable()
    status = BrowserRuntimeStatus(
        available=executable is not None,
        headless=settings.playwright_headless,
        browser_path=str(executable) if executable else None,
        browsers_dir=str(browsers_dir()),
        profile_dir=str(profile_dir()),
        detail=(
            "The browser runtime is installed and ready."
            if executable is not None
            else "The browser runtime is not installed yet - the browser adapter pauses its "
            "tasks until it is available."
        ),
        isolation=isolation_summary(),
    )
    return status


def install_runtime(timeout: int = 1800) -> tuple[bool, str]:
    """Install the Playwright package and the browser build on demand.

    Both end up in the application data directory, so nothing is written to
    the Python installation of the operating system and the browser of the
    user is never touched.  The progress is published through
    :func:`runtime_progress`, so the user interface can show what is happening
    instead of a silent wait.
    """
    with _INSTALL_LOCK:
        return _install_runtime(timeout)


def runtime_ready() -> bool:
    """The package *and* a browser build are available."""
    return playwright_available() and _find_browser_executable() is not None


#: The progress of the (single) runtime installation, read by the UI.
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, Any] = {
    "phase": "idle",
    "percent": None,
    "message": "",
    "detail": None,
    "started_at": None,
    "updated_at": None,
}


def _set_progress(
    phase: str,
    message: str,
    *,
    percent: float | None = None,
    detail: str | None = None,
) -> None:
    now = time.time()
    with _PROGRESS_LOCK:
        if phase in ("package", "browser") and not _PROGRESS.get("started_at"):
            _PROGRESS["started_at"] = now
        _PROGRESS.update(
            {
                "phase": phase,
                "message": message,
                "percent": percent,
                "detail": detail,
                "updated_at": now,
            }
        )


def runtime_progress() -> dict[str, Any]:
    """A snapshot of the install progress (safe to send to a client)."""
    with _PROGRESS_LOCK:
        snapshot = dict(_PROGRESS)
    started = snapshot.get("started_at")
    snapshot["elapsed"] = (
        round(time.time() - started, 1) if started else 0.0
    )
    snapshot.pop("started_at", None)
    snapshot.pop("updated_at", None)
    return snapshot


def reset_runtime_progress() -> None:
    """Forget the last install (used by tests)."""
    with _PROGRESS_LOCK:
        _PROGRESS.update(
            {
                "phase": "idle",
                "percent": None,
                "message": "",
                "detail": None,
                "started_at": None,
                "updated_at": None,
            }
        )


_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%\s+of\s+")


def _percent_from_line(line: str) -> float | None:
    """Read the percentage out of a Playwright download line."""
    match = _PERCENT.search(line)
    if match is None:
        return None
    try:
        value = float(match.group(1))
    except ValueError:  # pragma: no cover - regex guarantees a number
        return None
    return max(0.0, min(100.0, value))


def _run_streaming(
    command: list[str],
    *,
    env: dict[str, str] | None,
    timeout: int,
    phase: str,
    message: str,
) -> tuple[int, str]:
    """Run a command and publish its progress while it prints.

    The Playwright installer draws a progress bar with carriage returns, so
    the output is read in raw chunks and split on both ``\\r`` and ``\\n``.
    """
    try:
        process = subprocess.Popen(  # noqa: S603 - the caller builds the command
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        return 127, str(exc)
    assert process.stdout is not None

    # A download without output would block the read forever; the watchdog
    # kills it when the timeout is reached.
    watchdog = threading.Timer(timeout, process.kill)
    watchdog.daemon = True
    watchdog.start()
    output: list[str] = []
    pending = ""
    try:
        while True:
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            pending += chunk.decode("utf-8", "replace")
            parts = re.split(r"[\r\n]+", pending)
            pending = parts.pop()
            for part in parts:
                line = part.strip()
                if not line:
                    continue
                output.append(line)
                if len(output) > 500:
                    del output[:250]
                percent = _percent_from_line(line)
                if percent is not None:
                    detail = re.sub(r"^\s*[|■]+\s*", "", line)
                    _set_progress(phase, message, percent=percent, detail=detail)
        code = process.wait()
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
    return code, "\n".join(output[-80:])


def _install_runtime(timeout: int = 1800) -> tuple[bool, str]:
    packages = settings.data_dir / "py"
    packages.mkdir(parents=True, exist_ok=True)
    browsers = browsers_dir()

    # 1. The Playwright package (it brings its own driver).
    if not (packages / "playwright").is_dir():
        _set_progress("package", "Downloading the browser engine (Playwright)…")
        if not _ensure_pip():
            _set_progress("error", "pip is not available in this installation.")
            return False, "pip is not available in this installation."
        code, output = _run_streaming(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-compile",
                "--upgrade",
                "--target",
                str(packages),
                "playwright>=1.48",
            ],
            env=None,
            timeout=timeout,
            phase="package",
            message="Downloading the browser engine (Playwright)…",
        )
        if code != 0:
            _set_progress("error", "The Playwright package could not be installed.")
            return False, (
                "The Playwright package could not be installed.\n"
                f"{output[-800:]}"
            )

    # 2. The browser build itself.
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    env["PYTHONPATH"] = f"{packages}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    _set_progress("browser", "Downloading Chromium…", percent=0)
    log.info("downloading the browser runtime", extra={"extra_fields": {"dir": str(browsers)}})
    code, output = _run_streaming(
        command,
        env=env,
        timeout=timeout,
        phase="browser",
        message="Downloading Chromium…",
    )
    if code != 0:
        _set_progress("error", "The browser runtime could not be downloaded.")
        return False, (
            "The browser runtime could not be downloaded.\n"
            f"{output[-1500:]}"
        )
    _set_progress("done", "The browser is ready. Opening the login window…", percent=100)
    return True, (output or "The browser runtime was installed.")[-2000:]


def _ensure_pip() -> bool:
    """Make sure the interpreter can install packages."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ensurepip", "--default-pip"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode == 0:
            return True
    except Exception:  # pragma: no cover - defensive
        log.debug("ensurepip is not available")
    try:
        import pip  # noqa: F401

        return True
    except Exception:
        return False


def ensure_playwright_path() -> None:
    """Make an on demand installed Playwright importable.

    The Playwright *package* and its browser build live in the application
    data directory, not in the installation of the application, so importing
    it needs two things: the package directory on ``sys.path`` and the browser
    directory in the environment of the Playwright driver process.
    """
    packages = settings.data_dir / "py"
    if packages.is_dir():
        path = str(packages)
        if path not in sys.path:
            sys.path.insert(0, path)
    browsers = browsers_dir()
    try:
        installed = any(browsers.iterdir())
    except OSError:  # pragma: no cover - unreadable directory
        installed = False
    if installed:
        # Only point Playwright at this directory when a browser build is
        # really there; otherwise an empty directory would hide a browser the
        # user installed in the default cache.
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))


def playwright_available() -> bool:
    """Whether the Playwright package can be imported right now."""
    ensure_playwright_path()
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return True


#: The Chrome installation of the machine, per platform.  The login window
#: prefers it over the bundled Chromium because it is not started with the
#: automation flags that make Google refuse a sign-in.
_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
)


def chrome_executable() -> str | None:
    """The desktop Chrome of this machine (not a Playwright build)."""
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def launchable_chrome() -> str | None:
    """A full browser build that can be started as a normal application.

    Prefers the Chrome the operator already uses.  Falls back to the full
    Chromium build that :func:`install_runtime` downloaded (never the headless
    shell, which cannot show a window).
    """
    desktop = chrome_executable()
    if desktop is not None:
        return desktop
    downloaded = _find_browser_executable()
    if downloaded is None or downloaded.name in ("chrome-headless-shell", "headless_shell"):
        return None
    return str(downloaded)


def launch_options(headless: bool | None = None) -> dict[str, Any]:
    """The options that are used to start the isolated browser."""
    return {
        "headless": settings.playwright_headless if headless is None else bool(headless),
        "args": list(ISOLATION_ARGS),
        "user_data_dir": str(profile_dir()),
        "isolated": True,
    }


def isolated_environment() -> dict[str, str]:
    """The environment for the browser process.

    Variables that would point Playwright at the personal browser of the user
    (or at a running browser instance) are removed.
    """
    env = dict(os.environ)
    for key in list(env):
        if any(key.upper().startswith(prefix) for prefix in BLOCKED_ENV_PREFIXES):
            env.pop(key, None)
    env["PLAYWRIGHT_BROWSERS_PATH"] = playwright_browsers_path()
    # A fresh profile for every session of the automation browser.
    env["PLAYWRIGHT_USER_DATA_DIR"] = str(profile_dir())
    return env


def clean_profile() -> None:
    """Remove the throw away profile (for example after a crash)."""
    path = profile_dir()
    for child in path.glob("*"):
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive
            log.warning("could not clean the browser profile", extra={"extra_fields": {"path": str(child)}})


def describe_environment() -> str:
    """A short description of the isolation for the log file."""
    return json.dumps(
        {
            "profile": str(profile_dir()),
            "browsers": str(browsers_dir()),
            "headless": settings.playwright_headless,
        },
        indent=2,
    )


def temporary_profile() -> str:
    """A profile directory for a single browser session."""
    return tempfile.mkdtemp(prefix="autobacklinker-browser-", dir=str(settings.data_dir))
