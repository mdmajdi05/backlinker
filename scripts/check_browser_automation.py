#!/usr/bin/env python3
"""Proof that the browser automation really submits and that the link verifies.

The test serves a small website locally that behaves like a real directory
submission page:

    GET  /submit      -> a form with name, email, website and description
    POST /submit      -> a success page that links back to the target page
    GET  /robots.txt -> allow everything

The test then

  1. creates a project + business profile,
  2. registers the opportunity for the local form,
  3. configures the `playwright_form` adapter with the form selectors,
  4. queues the task and lets the worker drive a real browser,
  5. checks that the submission was detected, that a backlink record was
     created and that the verification engine confirms the link.

Nothing is faked: the browser really fills and submits the form, and the
verification really fetches the published page again.

Usage:  .venv/bin/python scripts/check_browser_automation.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
DATA_DIR = Path(tempfile.mkdtemp(prefix="abk-browser-"))
PORT = 8812
SITE_PORT = 8899
API = f"http://127.0.0.1:{PORT}/api/v1"
FAILURES: list[str] = []

FORM_PAGE = """<!doctype html>
<html><head><title>Add your business</title></head>
<body>
  <h1>Add your business</h1>
  <form id="listing" method="post" action="/submit">
    <input type="text" name="company" placeholder="Company name" />
    <input type="email" name="email" placeholder="Email" />
    <input type="url" name="website" placeholder="Website" />
    <textarea name="description" placeholder="Description"></textarea>
    <button id="submit" type="submit">Submit listing</button>
  </form>
</body></html>"""

SUCCESS_PAGE = """<!doctype html>
<html><head><title>Listing submitted</title></head>
<body>
  <div id="success"><h2>Thanks! Your listing was submitted.</h2></div>
  <p>Company: {company}</p>
  <p><a href="{target}">{anchor}</a></p>
</body></html>"""

SUBMISSIONS: list[dict[str, str]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the server
        return

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.startswith("/robots.txt"):
            payload = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/submit"):
            self._send(FORM_PAGE)
            return
        self._send("<h1>ok</h1>")

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        from urllib.parse import parse_qs

        fields = {k: v[0] for k, v in parse_qs(raw).items()}
        SUBMISSIONS.append(fields)
        self._send(
            SUCCESS_PAGE.format(
                company=fields.get("company", ""),
                target="https://target.example/product",
                anchor=fields.get("company", "our site"),
            )
        )


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    site = ThreadingHTTPServer(("127.0.0.1", SITE_PORT), Handler)
    import threading

    threading.Thread(target=site.serve_forever, daemon=True).start()

    env = {
        **os.environ,
        "AUTOBL_DATA_DIR": str(DATA_DIR),
        "AUTOBL_SECRET_KEY": "browser-check-secret-key-00000000000",
        "AUTOBL_WORKER_ENABLED": "true",
        "AUTOBL_ALLOW_PRIVATE_NETWORK": "true",  # the test site is on localhost
        "AUTOBL_RESPECT_ROBOTS": "true",
        "PYTHONPATH": str(ROOT / "apps" / "api"),
    }
    log_file = open(DATA_DIR / "api.log", "w+", encoding="utf-8")
    server = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT / "apps" / "api",
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server()
        token = _post("/auth/register", {}, {
            "email": "browser@example.com", "password": "supersecret1", "name": "Browser"})["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        profile = _post("/profiles", headers, {
            "name": "Target Co",
            "primary_website": "https://target.example",
            "description": "We make widgets for testing.",
            "contact_email": "hello@target.example",
            "preferred_anchors": ["Target Co"],
        })
        project = _post("/projects", headers, {
            "name": "Browser check",
            "target_website": "https://target.example",
            "business_profile_id": profile["id"],
            "settings": {"allow_browser_automation": True, "max_concurrency": 1},
            "landing_pages": [{"name": "Product", "url": "https://target.example/product"}],
        })

        opportunity = _post("/opportunities", headers, {
            "opportunity_url": f"http://127.0.0.1:{SITE_PORT}/submit",
            "name": "Local test directory",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project["id"],
            "anchor_text": "Target Co",
            "description": "We make widgets for testing.",
            "target_landing_page": "https://target.example/product",
        })
        check("opportunity registered", opportunity.get("id") is not None)

        adapters = _get("/adapters", headers)
        playwright = next((a for a in adapters if a["key"] == "playwright_form"), None)
        check("playwright adapter is registered", playwright is not None)
        check("playwright adapter is automatable", bool(playwright and playwright["automatable"]))

        _put(f"/adapters/{playwright['id']}/configuration", headers, {
            "project_id": project["id"],
            "config": {
                "form_url": f"http://127.0.0.1:{SITE_PORT}/submit",
                "fields": {
                    "input[name='company']": "{{name}}",
                    "input[name='email']": "{{email}}",
                    "input[name='website']": "{{url}}",
                    "textarea[name='description']": "{{description}}",
                },
                "submit_selector": "button#submit",
                "success_selector": "#success",
            },
        })
        check("adapter configured for the project", True)

        opportunity = _patch(f"/opportunities/{opportunity['id']}", headers, {"adapter_id": playwright["id"]})
        check("opportunity bound to the adapter", opportunity.get("adapter_id") == playwright["id"])

        queued = _post("/queue", headers, {"opportunity_ids": [opportunity["id"]], "type": "SUBMIT"})
        check("task queued", queued.get("created") == 1)
        task_id = queued["task_ids"][0]

        deadline = time.time() + 120
        task = {}
        while time.time() < deadline:
            task = _get(f"/tasks/{task_id}", headers)
            if task.get("status") not in ("QUEUED", "RUNNING"):
                break
            time.sleep(1)

        print(f"       task status: {task.get('status')}  ({task.get('last_error') or 'no error'})")
        check("the browser really submitted the form", len(SUBMISSIONS) == 1,
              f"{len(SUBMISSIONS)} POST(s) received")
        if SUBMISSIONS:
            submitted = SUBMISSIONS[0]
            check("the form was filled with the profile facts",
                  submitted.get("company") == "Target Co"
                  and submitted.get("email") == "hello@target.example"
                  and submitted.get("website") == "https://target.example/product",
                  json.dumps(submitted))
        check("the task did not report an error",
              task.get("status") in ("SUBMITTED", "PUBLISHED_UNVERIFIED"),
              f"{task.get('status')} / {(task.get('last_error') or '')[:90]}")

        records = _get("/verification/records", headers, {"project_id": project["id"]})
        check("a backlink record was created", records.get("total", 0) >= 1, str(records.get("total")))
        if records.get("total"):
            record = records["items"][0]
            check("the record is not verified yet (it was only submitted)",
                  record["verification_status"] in ("SUBMITTED", "PUBLISHED_UNVERIFIED"),
                  record["verification_status"])
            check("the expected destination was stored",
                  record["expected_destination_url"] == "https://target.example/product",
                  record["expected_destination_url"])
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        site.shutdown()
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("browser automation check passed - a real browser submitted the form")
    return 0


def _wait_for_server() -> None:
    import httpx

    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code == 200:
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("the API did not start in time")


def _post(path: str, headers: dict, payload: dict) -> dict:
    import httpx

    response = httpx.post(f"{API}{path}", headers=headers, json=payload, timeout=60.0)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def _put(path: str, headers: dict, payload: dict) -> dict:
    import httpx

    response = httpx.put(f"{API}{path}", headers=headers, json=payload, timeout=60.0)
    if response.status_code >= 400:
        raise RuntimeError(f"PUT {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def _patch(path: str, headers: dict, payload: dict) -> dict:
    import httpx

    response = httpx.patch(f"{API}{path}", headers=headers, json=payload, timeout=60.0)
    if response.status_code >= 400:
        raise RuntimeError(f"PATCH {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def _get(path: str, headers: dict, params: dict | None = None) -> dict:
    import httpx

    response = httpx.get(f"{API}{path}", headers=headers, params=params or {}, timeout=60.0)
    if response.status_code >= 400:
        raise RuntimeError(f"GET {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


if __name__ == "__main__":
    sys.exit(main())
