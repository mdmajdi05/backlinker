"""End to end check of the web login viewer (manual verification helper)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
WEB_DIR = ROOT / "apps" / "web"
PYTHON = ROOT / ".venv" / "bin" / "python"
API_PORT = 8000
WEB_PORT = 3000
API = f"http://127.0.0.1:{API_PORT}"
WEB = f"http://127.0.0.1:{WEB_PORT}"


def wait_for(client: httpx.Client, url: str, attempts: int = 120) -> None:
    for _ in range(attempts):
        try:
            response = client.get(url)
            if response.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{url} did not start")


def main() -> None:
    data_dir = tempfile.mkdtemp(prefix="abk-web-e2e-")
    env = {
        **os.environ,
        "AUTOBL_DATA_DIR": data_dir,
        "AUTOBL_ENVIRONMENT": "local",
        "AUTOBL_WORKER_ENABLED": "false",
        "AUTOBL_SECRET_KEY": "web-e2e-secret-key-000000000000000000",
    }
    api = subprocess.Popen(  # noqa: S603
        [str(PYTHON), "-m", "uvicorn", "app.main:app", "--port", str(API_PORT), "--log-level", "warning"],
        cwd=API_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    web = subprocess.Popen(  # noqa: S603
        ["npm", "run", "start"],
        cwd=WEB_DIR,
        env={**os.environ, "PATH": f"{Path.home() / '.local/node/bin'}:{os.environ['PATH']}"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        with httpx.Client(timeout=30) as client:
            wait_for(client, f"{API}/health")
            wait_for(client, f"{WEB}/login")

            registered = client.post(
                f"{API}/api/v1/auth/register",
                json={"email": "web@example.com", "password": "web-password-123", "name": "Web"},
            )
            registered.raise_for_status()
            token = registered.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            # The workspace gate sends a user without a business profile to
            # /onboarding; create one so the project page is reachable.
            profile = client.post(
                f"{API}/api/v1/profiles",
                json={"name": "Web stream", "primary_website": "https://web.example"},
                headers=headers,
            )
            profile.raise_for_status()
            project = client.post(
                f"{API}/api/v1/projects",
                json={"name": "Web stream project", "target_website": "https://web.example"},
                headers={"Authorization": f"Bearer {token}"},
            )
            project.raise_for_status()
            project_id = project.json()["id"]

            from playwright.sync_api import sync_playwright

            console_errors: list[str] = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                context.add_init_script(
                    "window.localStorage.setItem('abk.token', "
                    + json.dumps(token)
                    + ");"
                )
                page = context.new_page()

                def on_console(message: object) -> None:
                    if getattr(message, "type", "") == "error":
                        console_errors.append(getattr(message, "text", ""))

                page.on("console", on_console)
                page.on("pageerror", lambda error: console_errors.append(str(error)))
                page.goto(f"{WEB}/projects/{project_id}", wait_until="networkidle")
                page.get_by_text("Google login", exact=True).wait_for(timeout=20_000)
                page.get_by_role("button", name="Connect Google").click()

                dialog = page.get_by_role("dialog")
                dialog.wait_for(timeout=30_000)
                print("viewer:", dialog.get_attribute("aria-label"))

                # Wait for the live canvas and a real frame.
                canvas = dialog.locator("canvas")
                deadline = time.time() + 45
                pixels = 0
                while time.time() < deadline:
                    pixels = canvas.evaluate(
                        "(c) => {"
                        "  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;"
                        "  let n = 0;"
                        "  for (let i = 3; i < d.length; i += 4 * 97) { if (d[i] > 0) n += 1; }"
                        "  return n;"
                        "}"
                    )
                    if pixels > 0:
                        break
                    time.sleep(0.5)
                print("canvas:", pixels)
                if pixels <= 0:
                    raise SystemExit("no live frame reached the web canvas")

                dialog.get_by_role("button", name="Cancel").click()
                page.get_by_role("button", name="Cancel", exact=True).click()
                page.wait_for_timeout(1000)

            if console_errors:
                print("console errors:", console_errors[:5])
                raise SystemExit(1)
    finally:
        for process in (web, api):
            process.terminate()
            try:
                output, _ = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
            if process.returncode not in (0, -15):
                print(output[-3000:])


if __name__ == "__main__":
    main()
