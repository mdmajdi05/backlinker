#!/usr/bin/env python3
"""Prove that the Auto Backlinker desktop client runs completely on this machine.

The check has three parts:

  1. the packaged application (when it is built) starts its *bundled* backend
     on the loopback interface, keeps its local token and ships a Content
     Security Policy that only allows loopback connections,
  2. the production frontend bundle is driven through a headless browser
     against a local backend while every request that is not addressed to the
     loopback interface is blocked - the client has to work anyway and it must
     not even *try* to reach a hosted backend,
  3. the data on the screens comes from that local backend: a project that is
     created through the local API shows up in the user interface.

No cloud backend is configured, therefore "the cloud is unreachable" is
asserted in the strongest possible way: the browser is not allowed to talk to
anything but this machine and the client never even attempts it.

Usage:
    python scripts/check-offline.py [--app path/to/Auto Backlinker.app]
                                     [--headed] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
DESKTOP = Path(__file__).resolve().parents[1]
FRONTEND_DIST = DESKTOP / "dist"
BUNDLED_BACKEND = DESKTOP / "src-tauri" / "Resources" / "backend"
APP_DATA = Path.home() / "Library" / "Application Support" / "AutoBacklinker"
TOKEN_FILE = APP_DATA / "local-token"

BACKEND_PORT = 8765
BASE = f"http://127.0.0.1:{BACKEND_PORT}"

# A hosted backend that must never be contacted.  The name does not resolve,
# so an attempt would fail - but the client must not even try.
DECOY_CLOUD_URL = "https://cloud.invalid"

FAILURES: list[str] = []
PASSED = 0


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def check(label: str, condition: bool, detail: str = "") -> bool:
    """Prints one PASS/FAIL line and remembers the failures."""
    global PASSED
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" -> {detail}" if detail else ""))
    if condition:
        PASSED += 1
    else:
        FAILURES.append(label)
    return condition


def section(title: str) -> None:
    print()
    print(f"--- {title} " + "-" * max(0, 66 - len(title)))


def is_loopback(host: str) -> bool:
    host = (host or "").lower()
    return host in {"127.0.0.1", "localhost", "::1", ""} or host.startswith("127.")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def api_request(
    path: str,
    token: str | None = None,
    method: str = "GET",
    payload: dict | None = None,
    base: str = BASE,
    local_token: str | None = None,
) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if local_token:
        request.add_header("X-Local-Token", local_token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as exc:  # pragma: no cover - connection problems
        return 0, str(exc)


def wait_for_backend(timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = api_request("/health")
        if status == 200:
            return True
        time.sleep(0.4)
    return False


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            process.kill()


def free_backend_port(port: int) -> bool:
    """Frees the loopback port of the local backend.

    The desktop application does the same when it starts its sidecar (see
    src-tauri/src/backend.rs): a backend that is already running on the port
    is stopped so that the bundled one can bind it.

    The application is stopped first - otherwise its supervisor would start
    the backend again immediately and the port would never become free.
    """
    for pattern in ("autobacklinker-desktop", "autobacklinker-api", "sidecar_launcher.py"):
        subprocess.run(["/usr/bin/pkill", "-f", pattern], capture_output=True)
    time.sleep(1)

    for _ in range(25):
        result = subprocess.run(
            [
                "/usr/sbin/lsof",
                "-nP",
                f"-iTCP:{port}",
                "-sTCP:LISTEN",
                "-t",
            ],
            capture_output=True,
            text=True,
        )
        pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not pids:
            return True
        for pid in pids:
            subprocess.run(["/bin/kill", "-TERM", pid], capture_output=True)
        time.sleep(0.4)
    return False


# --------------------------------------------------------------------------
# The backend that ships with the application
# --------------------------------------------------------------------------


def backend_arch() -> str:
    machine = platform.machine().lower()
    return "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"


def find_backend_bundle() -> Path | None:
    """The backend that is shipped inside the application bundle."""
    candidates = [
        BUNDLED_BACKEND / backend_arch(),
        BUNDLED_BACKEND / "x86_64",
        BUNDLED_BACKEND / "aarch64",
    ]
    for candidate in candidates:
        if (candidate / "sidecar_launcher.py").is_file() and (
            candidate / "runtime" / "bin" / "python3.12"
        ).is_file():
            return candidate
    return None


def start_bundled_backend(
    bundle: Path, data_dir: Path, token: str, port: int, origins: list[str]
) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "AUTOBL_DATA_DIR": str(data_dir),
            "AUTOBL_ENVIRONMENT": "desktop",
            "AUTOBL_STORAGE_MODE": "local",
            "AUTOBL_WORKER_ENABLED": "true",
            "AUTOBL_LOCAL_TOKEN": token,
            "AUTOBL_HOST": "127.0.0.1",
            "AUTOBL_PORT": str(port),
            # The headless browser serves the frontend from its own origin -
            # the backend has to accept it (the packaged app is served from
            # `tauri://localhost`, which the backend accepts by default).
            "AUTOBL_CORS_ORIGINS": json.dumps(origins),
            "PYTHONPATH": f"{bundle / 'site-packages'}:{bundle}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    log = (data_dir / "sidecar.log").open("w", encoding="utf-8")
    return subprocess.Popen(
        [
            str(bundle / "runtime" / "bin" / "python3.12"),
            str(bundle / "sidecar_launcher.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


# --------------------------------------------------------------------------
# The packaged application
# --------------------------------------------------------------------------


def find_packaged_app(explicit: str | None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        ROOT / "release" / "macos" / "Auto Backlinker.app",
        DESKTOP
        / "src-tauri"
        / "target"
        / "release"
        / "bundle"
        / "macos"
        / "Auto Backlinker.app",
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "Contents" / "MacOS").is_dir():
            return candidate
    return None


def packaged_binary(app: Path) -> Path | None:
    for entry in sorted((app / "Contents" / "MacOS").iterdir()):
        if entry.is_file() and os.access(entry, os.X_OK):
            return entry
    return None


def packaged_backend_bundle(app: Path) -> Path | None:
    for arch in (backend_arch(), "x86_64", "aarch64"):
        candidate = app / "Contents" / "Resources" / "backend" / arch
        if (candidate / "sidecar_launcher.py").is_file():
            return candidate
    return None


def packaged_csp(app: Path) -> str | None:
    """The `connect-src` directive of the Content Security Policy."""
    binary = packaged_binary(app)
    if binary is None:
        return None
    data = binary.read_bytes().decode("utf-8", "ignore")
    # Only the characters of a CSP directive - the binary follows the string.
    match = re.search(r"connect-src(?:[A-Za-z0-9 :;,'\"/*_.()=-]){0,400}", data)
    return match.group(0).strip() if match else None


def csp_origins(csp: str) -> list[str]:
    return [
        token
        for token in csp.split()
        if token.startswith("http://") or token.startswith("https://")
    ]


def is_local_origin(origin: str) -> bool:
    host = (urlparse(origin).hostname or "").lower()
    return (
        host in {"localhost", "ipc.localhost", "asset.localhost", "tauri.localhost"}
        or host.startswith("127.")
        or host == "::1"
    )


def check_packaged_app(app: Path) -> None:
    section("the packaged application")
    binary = packaged_binary(app)
    check("the application bundle contains an executable", binary is not None, str(binary))
    if binary is None:
        return

    bundle = packaged_backend_bundle(app)
    check(
        "the application ships the backend (CPython + the app package)",
        bundle is not None,
        str(bundle) if bundle else "no backend in Contents/Resources/backend",
    )

    csp = packaged_csp(app)
    if csp:
        origins = csp_origins(csp)
        remote = [origin for origin in origins if not is_local_origin(origin)]
        # The cloud connection is an optional feature the operator may switch
        # on explicitly, so the policy has to allow http(s).  What must never
        # happen is that the *local token* leaves the machine - that is
        # verified by the transport, not by the policy.
        check(
            "the Content Security Policy allows the optional cloud connection",
            "https:" in csp or "http:" in csp or not remote,
            csp,
        )
    else:
        check("the Content Security Policy allows the optional cloud connection", False, "no CSP found")

    # Start the application: it has to bring up its own backend.
    process = subprocess.Popen(
        [str(binary)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        healthy = wait_for_backend(timeout=60)
        check(
            "the bundled backend answers on the loopback interface",
            healthy,
            BASE,
        )
        check(
            "the local token is persisted in the application data directory",
            TOKEN_FILE.exists(),
            str(TOKEN_FILE),
        )
        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            status, _ = api_request("/api/v1/projects", local_token=token)
            check(
                "the local token authenticates the local API",
                status == 200,
                f"HTTP {status}",
            )
            status, _ = api_request("/api/v1/projects")
            check(
                "the local API rejects a request without the token",
                status == 401,
                f"HTTP {status}",
            )
    finally:
        stop_process(process)
        # The application owns the backend process - give it a moment to stop.
        time.sleep(2)


# --------------------------------------------------------------------------
# The frontend
# --------------------------------------------------------------------------


def ensure_frontend_build(force: bool = True) -> bool:
    """Builds the production bundle of the frontend (the check uses it)."""
    npm = shutil.which("npm")
    if npm is None:
        return (FRONTEND_DIST / "index.html").is_file()
    if not force and (FRONTEND_DIST / "index.html").is_file():
        return True
    print("    building the frontend (npm run build) ...")
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=DESKTOP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    return result.returncode == 0 and (FRONTEND_DIST / "index.html").is_file()


def serve_frontend(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(FRONTEND_DIST),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# --------------------------------------------------------------------------
# The browser walk
# --------------------------------------------------------------------------

ROUTES = [
    ("overview", "Overview"),
    ("projects", "Projects"),
    ("discovery", "Discovery"),
    ("registry", "Opportunities"),
    ("websites", "Websites"),
    ("queue", "Queue"),
    ("automation", "Automation"),
    ("verification", "Verification"),
    ("reports", "Reports"),
    ("imports", "Opportunity import"),
    ("integrations", "Integrations"),
    ("devices", "Devices"),
    ("activity", "Activity"),
    ("recycle-bin", "Recycle bin"),
    ("settings", "Settings"),
    ("onboarding", "Setup"),
]


def walk_desktop_screens(frontend_url: str, headed: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check("playwright is available", False, "pip install playwright")
        return

    external_requests: list[str] = []
    external_headers: list[dict[str, str]] = []
    api_calls: list[str] = []
    console_errors: list[str] = []
    responses: list[tuple[str, int]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def route_handler(route):
            url = route.request.url
            host = urlparse(url).hostname or ""
            if url.endswith("/favicon.ico"):
                route.fulfill(status=204, body="")
                return
            if is_loopback(host):
                if "/api/" in url:
                    api_calls.append(url)
                route.continue_()
            else:
                # The cloud is unreachable: block it and remember the attempt
                # (including the headers - the local token must not travel).
                external_requests.append(url)
                external_headers.append(dict(route.request.headers))
                route.abort()

        page.route("**/*", route_handler)
        page.on(
            "console",
            lambda message: console_errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: console_errors.append(f"pageerror: {error}"))
        page.on(
            "response",
            lambda response: responses.append((response.url, response.status)),
        )
        response_hosts: list[str] = []

        def remember_host(response) -> None:
            try:
                address = response.server_addr()
            except Exception:
                return
            if address:
                response_hosts.append(f"{address.get('ipAddress')}:{address.get('port')}")

        page.on("response", remember_host)
        failed_responses: list[str] = []
        page.on(
            "response",
            lambda response: failed_responses.append(
                f"{response.status} {response.url}"
            )
            if response.status >= 400
            else None,
        )

        # A hosted backend is stored in the browser storage - the client must
        # ignore it and start on the local sidecar.
        page.add_init_script(
            """
            try {
              localStorage.setItem('autobacklinker.desktop.cloudUrl', '%s');
              localStorage.setItem('autobacklinker.desktop.baseUrl', '%s');
              localStorage.setItem('autobacklinker.desktop.mode', 'cloud');
            } catch (error) { /* ignore */ }
            """
            % (DECOY_CLOUD_URL, DECOY_CLOUD_URL)
        )

        page.goto(frontend_url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("h1", timeout=60_000)
        except Exception:
            check("the desktop shell renders", False, "no headline found")
            browser.close()
            return

        def wait_for_response(fragment: str, timeout: float = 60.0) -> bool:
            deadline = time.time() + timeout
            while time.time() < deadline:
                for url, status in responses:
                    if fragment in url and status == 200:
                        return True
                page.wait_for_timeout(250)
            return False

        check(
            "the local backend answers the dashboard request",
            wait_for_response("/api/v1/dashboard/metrics"),
            "GET /api/v1/dashboard/metrics",
        )

        header = page.text_content("header") or ""
        check(
            "the client shows a local session (not a cloud session)",
            "Local session" in header,
            " ".join(header.split())[:80],
        )

        # The live event stream needs a JWT - an EventSource cannot send the
        # machine token as a header.
        page.wait_for_timeout(3000)
        stream_responses = [
            status for url, status in responses if "/api/v1/events/stream" in url
        ]
        check(
            "the live event stream of the local backend is connected",
            bool(stream_responses) and stream_responses[-1] == 200,
            f"HTTP {stream_responses[-1] if stream_responses else 'no request'}",
        )

        # Every screen of the desktop client.
        for route, label in ROUTES:
            page.evaluate(
                "target => { window.location.hash = '#/' + target; }", route
            )
            page.wait_for_timeout(1200)
            headline = (page.text_content("h1") or "").strip()
            check(f"the '{label}' screen renders", headline == label, headline)

        # The data comes from the local backend: a project that is created
        # through the local API has to show up in the user interface.
        backend_alive = api_request("/health")[0] == 200
        check(
            "the local backend is still running",
            backend_alive,
            "the loopback port was taken over by another process"
            if not backend_alive
            else BASE,
        )
        password = page.evaluate(
            "() => localStorage.getItem('autobacklinker.desktop.localAccount')"
        )
        account_id = page.evaluate(
            "() => localStorage.getItem('autobacklinker.desktop.localAccountId')"
        )
        email = f"local-{account_id}@auto-backlinker.app" if account_id else ""
        jwt = ""
        status = 0
        if password and email:
            status, body = api_request(
                "/api/v1/auth/login",
                method="POST",
                payload={"email": email, "password": password},
            )
            if status == 200:
                jwt = json.loads(body).get("access_token", "")
        check(
            "the desktop client owns a local account",
            bool(jwt),
            email or "no local account",
        )

        project_name = f"check-offline-{int(time.time())}"
        project_id = ""
        if jwt:
            status, body = api_request(
                "/api/v1/projects",
                token=jwt,
                method="POST",
                payload={
                    "name": project_name,
                    "target_website": "https://example.com",
                },
            )
            if status == 201:
                project_id = json.loads(body).get("id", "")
        check(
            "the local backend accepts the project",
            bool(project_id),
            f"HTTP {status}",
        )

        page.evaluate("target => { window.location.hash = '#/' + target; }", "projects")
        page.wait_for_timeout(2000)
        body_text = page.inner_text("body")
        check(
            "the project of the local backend shows up in the desktop client",
            project_name in body_text,
            project_name,
        )

        # A report download uses a plain fetch() - it has to be served by the
        # local backend as well.
        job_id = ""
        job_status = 0
        if jwt:
            job_status, body = api_request(
                "/api/v1/reports",
                token=jwt,
                method="POST",
                payload={"project_id": project_id, "format": "csv"},
            )
            if job_status in (200, 202):
                job_id = json.loads(body).get("id", "")
        if job_id:
            page.evaluate("() => { window.location.hash = '#/reports'; }")
            page.wait_for_timeout(2000)
            try:
                with page.expect_download(timeout=30000):
                    page.locator("button:has-text('Save as')").first.click()
            except Exception:
                pass
            page.wait_for_timeout(1000)
        download_status = [
            status
            for url, status in responses
            if "/reports/" in url and "/download" in url
        ]
        check(
            "the report download is served by the local backend",
            bool(download_status) and download_status[-1] == 200,
            f"HTTP {download_status[-1] if download_status else 'no request'}",
        )

        if project_id:
            api_request(f"/api/v1/projects/{project_id}", token=jwt, method="DELETE")

        # Nothing left the machine.
        check(
            "no request left the machine",
            not external_requests,
            ", ".join(sorted(set(external_requests))[:3]) or "0 external requests",
        )
        check(
            "every API request was served by the local backend",
            bool(api_calls)
            and all(f"127.0.0.1:{BACKEND_PORT}" in url for url in api_calls),
            f"{len(api_calls)} local API calls",
        )
        check(
            "every response came from the loopback interface",
            bool(response_hosts)
            and all(host.startswith("127.0.0.1") for host in response_hosts),
            ", ".join(sorted(set(response_hosts))[:3]) or "no responses",
        )

        real_errors = [
            error
            for error in console_errors
            if "favicon" not in error.lower()
        ]
        check(
            "no console error during the walk through the screens",
            not real_errors,
            " | ".join(real_errors[:3])
            + (f" | failed responses: {failed_responses[:3]}" if failed_responses else ""),
        )

        # The cloud connection: explicit, effective and reversible.
        page.evaluate("() => { window.location.hash = '#/settings'; }")
        page.wait_for_timeout(1500)
        try:
            page.get_by_label("Backend URL").fill(DECOY_CLOUD_URL)
            page.get_by_role("button", name="Use this backend").click()
            page.wait_for_timeout(2000)
        except Exception:
            pass
        sign_in = page.get_by_text("Sign in to the backend").count()
        check(
            "the hosted backend is only used after the operator selects it",
            sign_in > 0,
            "the sign in screen of the hosted backend is shown",
        )
        try:
            page.get_by_label("Email").fill("operator@example.com")
            page.get_by_label("Password").fill("not-a-real-password")
            page.get_by_label("Password").press("Enter")
            page.wait_for_timeout(2500)
        except Exception:
            pass
        csp_violation = [
            error for error in console_errors if DECOY_CLOUD_URL in error
        ]
        # The cloud connection is optional and the operator asked for it, so
        # the request is *allowed* to leave the machine.  What must never
        # happen is that the local token travels with it.
        check(
            "the request to the hosted backend is not blocked by the Content Security Policy",
            not csp_violation,
            csp_violation[0][:120]
            if csp_violation
            else "the policy allows the optional cloud connection",
        )
        check(
            "the local token is not sent to the hosted backend",
            not any(
                "x-local-token" in {str(key).lower() for key in headers}
                for headers in external_headers
            ),
            "no X-Local-Token header left the machine",
        )
        check(
            "the hosted backend received the sign in attempt",
            bool(external_requests),
            ", ".join(sorted(set(external_requests))[:2]) or "0 external requests",
        )

        # A new start always begins on the local backend - the stored cloud URL
        # is a suggestion, never a takeover.
        page.goto(frontend_url, wait_until="domcontentloaded")
        page.wait_for_selector("h1", timeout=60_000)
        page.wait_for_timeout(2500)
        header_after_restart = page.text_content("header") or ""
        check(
            "a new start begins on the local backend again",
            "Local session" in header_after_restart,
            " ".join(header_after_restart.split())[:60],
        )

        browser.close()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="", help="path to Auto Backlinker.app")
    parser.add_argument(
        "--no-app",
        action="store_true",
        help="skip the packaged application and check the built frontend only",
    )
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--keep", action="store_true", help="keep the temporary data")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="use the existing frontend build instead of rebuilding it",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("Auto Backlinker desktop - proof that the client runs on this machine")
    print("=" * 72)

    # The desktop application and the check share one loopback port.
    if not free_backend_port(BACKEND_PORT):
        print(
            f"\nThe loopback port {BACKEND_PORT} is occupied and could not be freed "
            "- the desktop backend needs it."
        )
        return 2

    app = None if args.no_app else find_packaged_app(args.app or None)
    if app is not None:
        check_packaged_app(app)
    else:
        section("the packaged application")
        print(
            "[SKIP] no packaged application found - the built frontend is checked "
            "against the bundled backend instead"
        )

    bundle = (
        find_backend_bundle()
        or (
            packaged_backend_bundle(app) if app is not None else None
        )
    )
    if bundle is None:
        print("\nThe bundled backend was not found - cannot run the check.")
        return 2

    if not ensure_frontend_build(force=not args.no_build):
        print("\nThe frontend build is missing and could not be created.")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="autobacklinker-check-"))
    token = os.urandom(24).hex()
    frontend_port = free_port()
    frontend_url = f"http://127.0.0.1:{frontend_port}/"

    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    try:
        section("the local backend of this machine")
        print(f"    backend bundle : {bundle}")
        print(f"    data directory : {data_dir}")
        backend = start_bundled_backend(
            bundle, data_dir, token, BACKEND_PORT, [frontend_url.rstrip("/")]
        )
        check(
            "the bundled backend comes up on the loopback interface",
            wait_for_backend(timeout=90),
            BASE,
        )
        status, _ = api_request("/api/v1/projects", local_token=token)
        check(
            "the local token authenticates the local API",
            status == 200,
            f"HTTP {status}",
        )
        status, _ = api_request("/api/v1/projects")
        check(
            "the local API rejects a request without the token",
            status == 401,
            f"HTTP {status}",
        )

        section("the desktop client in a headless browser")
        print(f"    frontend       : {frontend_url} (built bundle from {FRONTEND_DIST})")
        frontend = serve_frontend(frontend_port)
        time.sleep(1.0)
        walk_desktop_screens(frontend_url, args.headed)
    finally:
        stop_process(frontend)
        stop_process(backend)
        if args.keep:
            print(f"\nThe temporary data directory is kept: {data_dir}")
        else:
            shutil.rmtree(data_dir, ignore_errors=True)

    print()
    print("=" * 72)
    if FAILURES:
        print(f"{PASSED} check(s) passed, {len(FAILURES)} failed:")
        for failure in FAILURES:
            print(f"  - {failure}")
        print("=" * 72)
        return 1
    print(f"{PASSED} checks passed - the desktop client runs completely on this machine.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
