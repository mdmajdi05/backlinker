#!/usr/bin/env python3
"""End-to-end check of the packaged desktop application.

It verifies the scenario that used to break:

  * the app is started, the bundled backend comes up on the loopback port,
  * the local token is persisted in the application data directory,
  * the app is started a second time while the backend is already running -
    no port conflict, no restart loop, exactly one backend,
  * the app is restarted completely - the token stays the same, so the token
    the UI holds is still valid and no request answers with 401.

Usage:
    python scripts/check-desktop.py [--app path/to/Auto Backlinker.app]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_DATA = Path.home() / "Library" / "Application Support" / "AutoBacklinker"
LOG_FILE = APP_DATA / "logs" / "backend.log"
TOKEN_FILE = APP_DATA / "local-token"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def http(path: str, token: str | None = None) -> tuple[int, str]:
    request = urllib.request.Request(f"{BASE}{path}")
    if token:
        request.add_header("X-Local-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as exc:  # pragma: no cover - connection problems
        return 0, str(exc)


def wait_for_backend(timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = http("/health")
        if status == 200:
            return True
        time.sleep(0.4)
    return False


def start_app(app_path: Path) -> subprocess.Popen:
    binary = app_path / "Contents" / "MacOS" / "autobacklinker-desktop"
    return subprocess.Popen(
        [str(binary)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop_app(process: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            process.kill()


def kill_strays() -> None:
    subprocess.run(["/usr/bin/pkill", "-f", "autobacklinker-desktop"], capture_output=True)
    subprocess.run(["/usr/bin/pkill", "-f", "autobacklinker-api"], capture_output=True)
    time.sleep(3)


def listeners_on_port() -> int:
    result = subprocess.run(["/usr/sbin/lsof", "-ti", f":{PORT}"], capture_output=True, text=True)
    return len([line for line in result.stdout.splitlines() if line.strip()])


def main() -> int:
    parser = argparse.ArgumentParser()
    default_app = (
        Path(__file__).resolve().parents[3] / "release" / "macos" / "Auto Backlinker.app"
    )
    parser.add_argument("--app", default=str(default_app))
    args = parser.parse_args()
    app_path = Path(args.app)

    if not app_path.exists():
        print(f"The application bundle was not found at {app_path}", file=sys.stderr)
        return 2

    print(f"Testing {app_path}")
    kill_strays()
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    # -- 1. first launch -------------------------------------------------
    first = start_app(app_path)
    check("the backend answers after the first launch", wait_for_backend(), BASE)
    check("the local token was persisted", TOKEN_FILE.exists(), str(TOKEN_FILE))
    token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
    check("the token is not empty", len(token) >= 16, f"{len(token)} characters")

    status, _ = http("/api/v1/projects", token)
    check("a request with the token is accepted", status == 200, f"HTTP {status}")
    status, _ = http("/api/v1/projects")
    check("a request without the token is rejected", status == 401, f"HTTP {status}")

    # -- 2. second launch while the backend runs -------------------------
    second = start_app(app_path)
    time.sleep(14)
    log = LOG_FILE.read_text(encoding="utf-8", errors="replace") if LOG_FILE.exists() else ""
    check("no port conflict", "address already in use" not in log)
    check("no restart loop", "exited unexpectedly" not in log)
    check("exactly one backend listens on the port", listeners_on_port() == 1,
          f"{listeners_on_port()} listener(s)")
    check("the token did not change", TOKEN_FILE.read_text().strip() == token)

    # -- 3. full restart --------------------------------------------------
    stop_app(second)
    stop_app(first)
    time.sleep(4)
    third = start_app(app_path)
    check("the backend comes up again after a restart", wait_for_backend(), BASE)
    check("the token is still the same after a restart",
          TOKEN_FILE.read_text().strip() == token)
    status, _ = http("/api/v1/projects", token)
    check("the token the UI holds is still valid (no 401 after a restart)",
          status == 200, f"HTTP {status}")

    stop_app(third)
    time.sleep(2)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("desktop check passed - the packaged app starts, reuses the backend and keeps its session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
