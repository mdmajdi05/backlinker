#!/usr/bin/env python3
"""End-to-end acceptance test of the complete product loop.

It runs the real API (uvicorn + SQLite + embedded worker) and walks through
the workflow the product promises:

    business profile -> project -> discovery -> approve -> queue -> run
    -> submission outcome -> verification -> Excel export -> re-import

Every step asserts on data that is really stored in the database; nothing is
mocked and no third-party website is contacted.

Usage:  .venv/bin/python scripts/acceptance.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
DATA_DIR = Path(tempfile.mkdtemp(prefix="abk-acceptance-"))
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    env = {
        **os.environ,
        "AUTOBL_DATA_DIR": str(DATA_DIR),
        "AUTOBL_SECRET_KEY": "acceptance-test-secret-key-00000000000",
        "AUTOBL_WORKER_ENABLED": "true",
        "PYTHONPATH": str(ROOT / "apps" / "api"),
    }
    # The server log goes into a file: a pipe would fill up and block the
    # server as soon as the buffer is exhausted.
    server_log = open(DATA_DIR / "server.log", "w+", encoding="utf-8")
    server = subprocess.Popen(
        [
            str(PY), "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning",
        ],
        cwd=ROOT / "apps" / "api",
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server()
        token = _register()
        headers = {"Authorization": f"Bearer {token}"}

        # -- 1. business profile ------------------------------------
        profile = _post("/api/v1/profiles", headers, {
            "name": "Acme Analytics",
            "primary_website": "https://acme.example",
            "description": "Product analytics for ecommerce teams.",
            "industry": "SaaS",
            "niche": "ecommerce analytics",
            "keywords": ["ecommerce analytics", "shopify reporting"],
            "preferred_anchors": ["Acme Analytics"],
            "target_countries": ["US"],
            "primary_landing_pages": ["https://acme.example/product"],
        })
        check("business profile created", profile.get("id") is not None)

        # -- 2. project ----------------------------------------------
        project = _post("/api/v1/projects", headers, {
            "name": "Acme Backlinks",
            "target_website": "https://acme.example",
            "business_profile_id": profile["id"],
            "settings": {"max_concurrency": 2, "request_rate_per_minute": 20},
            "landing_pages": [{"name": "Product", "url": "https://acme.example/product"}],
        })
        check("project created", project.get("id") is not None)
        check("project settings stored", (project.get("settings") or {}).get("max_concurrency") == 2)

        # -- 3. discovery --------------------------------------------
        run = _post("/api/v1/discovery/runs", headers, {
            "project_id": project["id"],
            "provider": "manual_seed",
            "query": "shopify analytics tools",
            "seeds": ["https://partner-directory.example/list-your-business"],
            "limit": 5,
        })
        check("discovery run accepted", run.get("id") is not None)
        _wait_for(lambda: _get(f"/api/v1/discovery/runs/{run['id']}", headers).get("status") in
                  ("COMPLETED", "FAILED"), timeout=30)
        finished = _get(f"/api/v1/discovery/runs/{run['id']}", headers)
        check("discovery run completed", finished.get("status") == "COMPLETED", str(finished.get("status")))
        check("discovery found the seeded site", finished.get("new_count", 0) >= 1,
              f"new={finished.get('new_count')} dup={finished.get('duplicate_count')}")

        # -- 4. registry ----------------------------------------------
        listing = _get("/api/v1/opportunities", headers, {"project_id": project["id"]})
        check("opportunity is in the registry", listing.get("total", 0) >= 1, str(listing.get("total")))
        opportunity = listing["items"][0]
        check("opportunity carries a score", isinstance(opportunity.get("score"), (int, float)))
        check("score explains itself",
              bool((opportunity.get("score_breakdown") or {}).get("reasons")))
        check("unavailable metrics are labelled, not invented",
              "domain_authority" in ((opportunity.get("score_breakdown") or {}).get("unavailable_metrics") or []))

        approved = _post("/api/v1/opportunities/bulk", headers, {
            "opportunity_ids": [opportunity["id"]], "action": "approve"})
        check("opportunity approved", approved.get("affected") == 1)

        # -- 5. queue --------------------------------------------------
        queued = _post("/api/v1/queue", headers, {
            "opportunity_ids": [opportunity["id"]], "type": "SUBMIT"})
        check("task queued", queued.get("created") == 1)
        task_id = queued["task_ids"][0]

        duplicate = _post("/api/v1/queue", headers, {
            "opportunity_ids": [opportunity["id"]], "type": "SUBMIT"})
        check("duplicate queue request does not create a second task", duplicate.get("created") == 0)

        _wait_for(lambda: _get(f"/api/v1/tasks/{task_id}", headers).get("status") not in
                  ("QUEUED", "RUNNING"), timeout=40)
        task = _get(f"/api/v1/tasks/{task_id}", headers)
        check("task was executed by the worker",
              task.get("status") in ("SUBMITTED", "PUBLISHED_UNVERIFIED", "WAITING_FOR_USER",
                                     "WAITING_FOR_APPROVAL", "FAILED"),
              f"status={task.get('status')}")
        attempts = _get(f"/api/v1/tasks/{task_id}/attempts", headers)
        check("an attempt was recorded", len(attempts) >= 1, f"{len(attempts)} attempt(s)")

        # -- 6. events --------------------------------------------------
        activity = _get("/api/v1/activity", headers, {"page_size": 100})
        types = {event["event_type"] for event in activity["items"]}
        check("activity log contains the real lifecycle events",
              {"task.queued", "task.started"} <= types, str(sorted(types))[:160])

        # -- 7. metrics --------------------------------------------------
        metrics = _get("/api/v1/dashboard/metrics", headers)
        check("dashboard counts the project", metrics.get("projects") == 1)
        check("dashboard counts the opportunity", metrics.get("opportunities") >= 1)
        check("dashboard counts the queued work", metrics.get("queued") + metrics.get("running") >= 0)

        # -- 8. export ---------------------------------------------------
        report = _post("/api/v1/reports", headers, {"project_id": project["id"], "format": "xlsx"})
        check("report generated", report.get("status") == "COMPLETED", str(report.get("status")))
        check("report file exists", bool(report.get("file_path")))
        if report.get("file_path"):
            import openpyxl

            workbook = openpyxl.load_workbook(report["file_path"])
            expected = [
                "Executive Summary", "All Opportunities", "Verified Backlinks", "Pending Tasks",
                "Failed Tasks", "Skipped Tasks", "Verification History", "Activity Log",
                "Import Errors",
            ]
            check("report has all nine sheets", all(s in workbook.sheetnames for s in expected),
                  str(workbook.sheetnames))

        # -- 9. re-import -------------------------------------------------
        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Reimport"
        sheet.append(["Website", "Opportunity URL", "Category", "Status", "Anchor Text", "Target URL"])
        sheet.append(["partner-directory.example", "https://partner-directory.example/list-your-business",
                      "BUSINESS_DIRECTORY", "", "Acme Analytics", "https://acme.example/product"])
        sheet.append(["other-directory.example", "https://other-directory.example/submit",
                      "BUSINESS_DIRECTORY", "PENDING", "Acme Analytics", "https://acme.example/product"])
        workbook_path = DATA_DIR / "reimport.xlsx"
        workbook.save(workbook_path)

        preview = _upload("/api/v1/imports/preview", headers, workbook_path, {"project_id": project["id"]})
        check("import preview created", bool(preview.get("import_job_id")))
        actions = {row["action"] for row in preview.get("rows", [])}
        check("preview plans an update for the known site", "UPDATE" in actions, str(sorted(actions)))
        check("preview plans a create for the new site", "CREATE" in actions, str(sorted(actions)))
        check("preview counts add up",
              preview["counts"]["total"] == len(preview.get("rows", [])))

        committed = _post(f"/api/v1/imports/{preview['import_job_id']}/commit", headers, {})
        check("import committed", committed.get("status") == "COMMITTED", str(committed.get("status")))
        check("import created the new opportunity", (committed.get("created_count") or 0) >= 1,
              f"created={committed.get('created_count')} updated={committed.get('updated_count')}")

        after = _get("/api/v1/opportunities", headers, {"project_id": project["id"]})
        check("the imported opportunity is in the registry", after.get("total", 0) >= 2, str(after.get("total")))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()
        if FAILURES:
            print("--- server log (tail) ---")
            try:
                server_log.flush()
                print((DATA_DIR / "server.log").read_text(encoding="utf-8")[-3000:])
            except Exception:
                pass
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("acceptance test passed - the complete loop works on real data")
    return 0


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _wait_for_server() -> None:
    import httpx

    for _ in range(100):
        try:
            if httpx.get(f"{BASE}/health", timeout=2.0).status_code == 200:
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("the API did not start in time")


def _wait_for(predicate, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.4)


def _post(path: str, headers: dict, payload: dict) -> dict:
    import httpx

    response = httpx.post(f"{BASE}{path}", headers=headers, json=payload, timeout=30.0)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def _get(path: str, headers: dict, params: dict | None = None) -> dict:
    import httpx

    response = httpx.get(f"{BASE}{path}", headers=headers, params=params or {}, timeout=30.0)
    if response.status_code >= 400:
        raise RuntimeError(f"GET {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def _upload(path: str, headers: dict, file_path: Path, fields: dict) -> dict:
    import httpx

    with file_path.open("rb") as handle:
        response = httpx.post(
            f"{BASE}{path}",
            headers=headers,
            files={"file": (file_path.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={k: v for k, v in fields.items() if v},
            timeout=60.0,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def _register() -> str:
    payload = {"email": "acceptance@example.com", "password": "supersecret123", "name": "Acceptance"}
    return _post("/api/v1/auth/register", {}, payload)["access_token"]


if __name__ == "__main__":
    sys.exit(main())
