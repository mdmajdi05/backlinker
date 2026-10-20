"""End to end smoke test of the core API (no external network required).

Run with:  ../../.venv/bin/python scripts/smoke_core.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(tempfile.mkdtemp(prefix="abk-smoke-"))
os.environ["AUTOBL_DATA_DIR"] = str(DATA_DIR)
os.environ["AUTOBL_SECRET_KEY"] = "smoke-test-secret"
os.environ["AUTOBL_WORKER_ENABLED"] = "true"

from fastapi.testclient import TestClient

from app.main import app


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        globals()["FAILURES"] = globals().get("FAILURES", 0) + 1


def main() -> int:
    failures = 0
    with TestClient(app) as client:
        # --- auth ------------------------------------------------------
        register = client.post(
            "/api/v1/auth/register",
            json={"email": "operator@example.com", "password": "supersecret123", "name": "Operator"},
        )
        check("register returns 201", register.status_code == 201, str(register.status_code))
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        check("unauthenticated request is rejected", client.get("/api/v1/projects").status_code == 401)
        duplicate = client.post(
            "/api/v1/auth/register",
            json={"email": "operator@example.com", "password": "supersecret123", "name": "Dup"},
        )
        check("duplicate registration is rejected", duplicate.status_code == 409)

        # --- business profile -----------------------------------------
        profile = client.post(
            "/api/v1/profiles",
            headers=headers,
            json={
                "name": "Acme Analytics",
                "primary_website": "acme-analytics.example",
                "description": "Analytics platform for ecommerce teams",
                "industry": "SaaS",
                "niche": "ecommerce analytics",
                "keywords": ["ecommerce analytics", "shopify reporting"],
                "preferred_anchors": ["Acme Analytics", "acme analytics tool"],
                "target_countries": ["US", "GB"],
            },
        )
        check("profile created", profile.status_code == 201, profile.text[:160])
        profile_id = profile.json()["id"]

        # --- project ----------------------------------------------------
        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "name": "Acme Backlinks",
                "target_website": "https://acme-analytics.example",
                "business_profile_id": profile_id,
                "settings": {"max_concurrency": 2, "request_rate_per_minute": 20},
                "landing_pages": [{"name": "Product", "url": "https://acme-analytics.example/product"}],
            },
        )
        check("project created", project.status_code == 201, project.text[:160])
        project_id = project.json()["id"]
        check("project has settings", project.json()["settings"] is not None)

        # --- registry ---------------------------------------------------
        opportunity = client.post(
            "/api/v1/opportunities",
            headers=headers,
            json={
                "opportunity_url": "https://directory.example.org/add-your-business",
                "name": "Directory Example",
                "category": "BUSINESS_DIRECTORY",
                "project_id": project_id,
                "anchor_text": "Acme Analytics",
            },
        )
        check("opportunity created", opportunity.status_code == 201, opportunity.text[:200])
        opportunity_id = opportunity.json()["id"]

        listing = client.get("/api/v1/opportunities", headers=headers, params={"project_id": project_id})
        check("opportunity listed", listing.status_code == 200 and listing.json()["total"] >= 1)

        approve = client.post(
            "/api/v1/opportunities/bulk",
            headers=headers,
            json={"opportunity_ids": [opportunity_id], "action": "approve"},
        )
        check("bulk approve works", approve.status_code == 200 and approve.json()["affected"] == 1)

        # --- queue ------------------------------------------------------
        queued = client.post(
            "/api/v1/queue",
            headers=headers,
            json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"},
        )
        check("task queued", queued.status_code == 200 and queued.json()["created"] == 1, queued.text[:160])
        task_id = queued.json()["task_ids"][0]

        again = client.post(
            "/api/v1/queue",
            headers=headers,
            json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"},
        )
        check("duplicate queue request is idempotent", again.json()["created"] == 0)

        stats = client.get("/api/v1/queue/stats", headers=headers).json()
        check("queue stats available", stats.get("TOTAL", 0) >= 1, str(stats))

        control = client.post(
            f"/api/v1/queue/{task_id}/control",
            headers=headers,
            json={"action": "cancel"},
        )
        check("task cancel works", control.status_code == 200 and control.json()["status"] == "CANCELLED")

        # --- dashboard ---------------------------------------------------
        metrics = client.get("/api/v1/dashboard/metrics", headers=headers).json()
        check("metrics projects == 1", metrics["projects"] == 1, str(metrics.get("projects")))
        check("metrics opportunities >= 1", metrics["opportunities"] >= 1)
        check("metrics has categories", isinstance(metrics["by_category"], list))

        # --- activity ----------------------------------------------------
        activity = client.get("/api/v1/activity", headers=headers)
        check("activity feed returns events", activity.status_code == 200 and activity.json()["total"] >= 1)

        # --- storage -----------------------------------------------------
        storage = client.get("/api/v1/storage/status", headers=headers).json()
        check("storage mode is local by default", storage["mode"] in ("LOCAL", "HYBRID"), str(storage["mode"]))
        check("storage uses sqlite", storage["database_type"] == "sqlite")

        backup = client.post("/api/v1/storage/backup", headers=headers)
        check("backup created", backup.status_code == 200 and Path(backup.json()["path"]).exists())

        # --- health -------------------------------------------------------
        health = client.get("/health").json()
        check("health ok", health["status"] == "ok")

    print()
    print("smoke test finished")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
