#!/usr/bin/env python3
"""Start a real backlink campaign for one website.

It does exactly what the user interface does, only through the API:

  1. create the business profile (the facts of the business),
  2. create the project (the page that should receive the backlink),
  3. run the discovery providers (the built-in catalogue + the seeds),
  4. show the opportunities that were found, with their score.

Usage:
    .venv/bin/python scripts/start_campaign.py --website https://servchip.com \
        --name "Servchip" --description "AI chip distributor ..." \
        --keywords "ai chips,gpu distributor,semiconductor supplier" \
        --seeds https://www.thomasnet.com/ https://www.europages.co.uk/
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

API = "http://127.0.0.1:8000/api/v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=API)
    parser.add_argument("--email", default="owner@servchip.com")
    parser.add_argument("--password", default="servchip-demo-2026")
    parser.add_argument("--name", default="Servchip")
    parser.add_argument("--website", default="https://servchip.com")
    parser.add_argument("--description", default="")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--anchor", default="Servchip")
    parser.add_argument("--seeds", nargs="*", default=[])
    parser.add_argument("--providers", nargs="*", default=["directory_index", "manual_seed"])
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    client = httpx.Client(timeout=90.0)
    base = args.base.rstrip("/")

    def post(path: str, payload: dict, token: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = client.post(f"{base}{path}", json=payload, headers=headers)
        if response.status_code == 409:
            return {}
        response.raise_for_status()
        return response.json()

    def get(path: str, token: str, params: dict | None = None) -> dict:
        response = client.get(f"{base}{path}", headers={"Authorization": f"Bearer {token}"}, params=params or {})
        response.raise_for_status()
        return response.json()

    # 1. the user ---------------------------------------------------------
    token = post(
        "/auth/register",
        {"email": args.email, "password": args.password, "name": args.name},
    ).get("access_token")
    if not token:
        login = client.post(
            f"{base}/auth/login", json={"email": args.email, "password": args.password}
        )
        login.raise_for_status()
        token = login.json()["access_token"]
    print(f"1. signed in as {args.email}")

    # 2. the business profile ---------------------------------------------
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    profiles = get("/profiles", token)
    profile = None
    for candidate in profiles:
        if candidate["primary_website"].rstrip("/") == args.website.rstrip("/"):
            profile = candidate
            break
    if profile is None:
        profile = post(
            "/profiles",
            {
                "name": args.name,
                "primary_website": args.website,
                "description": args.description,
                "industry": "Semiconductors / Electronics distribution",
                "niche": "AI chips, GPUs and accelerators",
                "keywords": keywords,
                "preferred_anchors": [args.anchor, "Servchip AI chip distributor"],
                "business_descriptions": [
                    args.description
                    or "Servchip supplies AI chips, GPUs and accelerators with certified "
                    "procurement and engineering support."
                ],
                "author_bios": [
                    "The Servchip team - AI chip distribution with certified procurement "
                    "and engineering support."
                ],
                "target_countries": ["US", "AE", "GB", "DE"],
                "preferred_categories": [
                    "INDUSTRY_DIRECTORY",
                    "SUPPLIER_PARTNER",
                    "BUSINESS_DIRECTORY",
                    "BUSINESS_PROFILE",
                    "RESOURCE_PAGE",
                ],
                "contact_email": args.email,
                "target_domains": ["nvidia.com", "amd.com", "intel.com"],
            },
            token,
        )
        print(f"2. business profile created: {profile.get('name')}")
    else:
        print(f"2. business profile reused: {profile.get('name')}")

    # 3. the project ------------------------------------------------------
    projects = get("/projects", token)
    project = None
    for candidate in projects["items"]:
        if candidate["target_website"].rstrip("/") == args.website.rstrip("/"):
            project = candidate
            break
    if project is None:
        project = post(
            "/projects",
            {
                "name": f"{args.name} backlinks",
                "description": "Backlinks for the AI chip distribution business",
                "target_website": args.website,
                "business_profile_id": profile["id"],
                "settings": {"max_concurrency": 2, "request_rate_per_minute": 15, "max_retries": 3},
                "landing_pages": [
                    {"name": "Home", "url": args.website, "kind": "MAIN"},
                    {"name": "AI chips", "url": f"{args.website.rstrip('/')}/ai-chips", "kind": "LANDING"},
                ],
            },
            token,
        )
        print(f"3. project created: {project.get('name')}")
    else:
        print(f"3. project reused: {project.get('name')}")

    # 4. discovery --------------------------------------------------------
    for provider in args.providers:
        payload = {
            "project_id": project["id"],
            "provider": provider,
            "query": " ".join(keywords[:3]) or "ai chip distributor",
            "keywords": keywords,
            "limit": args.limit,
            "config": {"probe_budget": 12},
        }
        if provider == "manual_seed" and args.seeds:
            payload["seeds"] = args.seeds
        run = post("/discovery/runs", payload, token)
        print(f"4. discovery started: {provider} (run {run.get('id')})")

    # 5. wait and report --------------------------------------------------
    print("\n   waiting for the workers ...")
    deadline = time.time() + 120
    runs = get("/discovery/runs", token, {"project_id": project["id"], "page_size": 20})["items"]
    while time.time() < deadline:
        runs = get("/discovery/runs", token, {"project_id": project["id"], "page_size": 20})["items"]
        if all(run["status"] in ("COMPLETED", "FAILED", "CANCELLED") for run in runs) and runs:
            break
        time.sleep(2)

    print()
    for run in runs:
        print(
            f"   {run['provider']:16} {run['status']:10} "
            f"found={run['discovered_count']} new={run['new_count']} dup={run['duplicate_count']}"
            + (f"  error={run['error'][:80]}" if run.get("error") else "")
        )

    opportunities = get(
        "/opportunities", token, {"project_id": project["id"], "page_size": 100}
    )["items"]
    print(f"\n5. {len(opportunities)} opportunities are now in the review list:\n")
    print(f"   {'score':>5}  {'domain':34} {'category':22} {'method':12} url")
    for item in sorted(opportunities, key=lambda row: -row["score"]):
        print(
            f"   {item['score']:5.1f}  {item['domain'][:34]:34} {item['category'][:22]:22} "
            f"{item['submission_method'][:12]:12} {item['opportunity_url'][:58]}"
        )

    print(
        f"\n   project id  : {project['id']}\n"
        f"   profile id  : {profile['id']}\n"
        f"   open        : http://localhost:3000/registry?project_id={project['id']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
