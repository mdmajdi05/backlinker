#!/usr/bin/env python3
"""Fill a running backend with a small, real demo workspace.

It creates

  * a demo user (login: demo@example.com / demo123456),
  * a business profile,
  * two projects,
  * a handful of opportunities (one of them added manually, exactly the way
    the "Add website" dialog does it),
  * a discovery run,
  * one queued task.

Nothing is faked - every row is written through the public REST API, so the
same flow works from the user interface.

Usage:
    .venv/bin/python scripts/seed_demo.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

EMAIL = "demo@example.com"
PASSWORD = "demo123456"

OPPORTUNITIES = [
    {
        "name": "Shopify App Store",
        "opportunity_url": "https://apps.shopify.com/",
        "category": "BUSINESS_DIRECTORY",
        "description": "Public listing of Shopify apps with a link back to the product page.",
    },
    {
        "name": "G2 - Product directory",
        "opportunity_url": "https://www.g2.com/",
        "category": "INDUSTRY_DIRECTORY",
        "description": "Software directory for B2B buyers.",
    },
    {
        "name": "Product Hunt",
        "opportunity_url": "https://www.producthunt.com/",
        "category": "BUSINESS_PROFILE",
        "description": "Product launch platform.",
    },
    {
        "name": "Awesome Shopify Apps list",
        "opportunity_url": "https://github.com/",
        "category": "RESOURCE_PAGE",
        "description": "Curated list of Shopify apps.",
    },
    {
        "name": "Local Chamber of Commerce",
        "opportunity_url": "https://www.chamberofcommerce.com/",
        "category": "LOCAL_CITATION",
        "description": "Local business listing.",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    api = f"{base}/api/v1"

    client = httpx.Client(timeout=60.0)

    def post(path: str, payload: dict, token: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = client.post(f"{api}{path}", json=payload, headers=headers)
        if response.status_code == 409:
            return {}
        response.raise_for_status()
        return response.json()

    def get(path: str, token: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = client.get(f"{api}{path}", headers=headers)
        response.raise_for_status()
        return response.json()

    # 1. user -------------------------------------------------------------
    token = post("/auth/register", {"email": EMAIL, "password": PASSWORD, "name": "Demo Operator"}).get(
        "access_token"
    )
    if not token:
        login = client.post(f"{api}/auth/login", json={"email": EMAIL, "password": PASSWORD})
        login.raise_for_status()
        token = login.json()["access_token"]
    print(f"user        : {EMAIL} / {PASSWORD}")

    profiles = get("/profiles", token)
    if profiles:
        profile = profiles[0]
        print(f"profile     : {profile['name']} (already there)")
    else:
        profile = post("/profiles", {
            "name": "Acme Analytics",
            "primary_website": "https://acme-analytics.example",
            "description": "Product analytics for ecommerce and Shopify teams.",
            "industry": "SaaS",
            "niche": "ecommerce analytics",
            "keywords": ["ecommerce analytics", "shopify reporting", "conversion tracking"],
            "preferred_anchors": ["Acme Analytics", "Acme analytics tool"],
            "business_descriptions": [
                "Acme Analytics helps Shopify stores understand revenue, conversion and retention."
            ],
            "author_bios": ["Product team at Acme Analytics, 40+ Shopify stores."],
            "target_countries": ["US", "GB", "CA"],
            "preferred_categories": ["BUSINESS_DIRECTORY", "INDUSTRY_DIRECTORY", "RESOURCE_PAGE"],
            "contact_email": "hello@acme-analytics.example",
        }, token)
        print(f"profile     : {profile['name']}")

    # 2. projects ----------------------------------------------------------
    project = post("/projects", {
        "name": "Acme Backlinks",
        "description": "Directories and industry listings",
        "target_website": "https://acme-analytics.example",
        "business_profile_id": profile["id"],
        "settings": {"max_concurrency": 2, "request_rate_per_minute": 20},
        "landing_pages": [{"name": "Product", "url": "https://acme-analytics.example/product"}],
    }, token) or get("/projects", token)["items"][0]
    print(f"project A   : {project['name']}")

    post("/projects", {
        "name": "Acme Editorial",
        "description": "Guest posts and resource pages",
        "target_website": "https://acme-analytics.example/blog",
        "business_profile_id": profile["id"],
        "settings": {"max_concurrency": 1},
    }, token)

    # 3. opportunities -----------------------------------------------------
    existing = {item["domain"] for item in get("/opportunities", token)["items"]}
    added = 0
    for item in OPPORTUNITIES:
        if item["opportunity_url"].split("/")[2] in existing:
            continue
        post("/opportunities", {
            **item,
            "project_id": project["id"],
            "anchor_text": "Acme Analytics",
            "target_landing_page": "https://acme-analytics.example/product",
        }, token)
        added += 1
    print(f"opportunities: {added} added")

    # 4. a discovery run ---------------------------------------------------
    run = post("/discovery/runs", {
        "project_id": project["id"],
        "provider": "manual_seed",
        "query": "shopify analytics directories",
        "seeds": ["https://partner-directory.example/list-your-business"],
        "limit": 3,
    }, token)
    if run:
        print(f"discovery   : run {run['id']} started")

    # 5. queue one approved task -------------------------------------------
    opportunities = get("/opportunities", token)["items"]
    if opportunities:
        target = opportunities[0]
        post("/opportunities/bulk", {"opportunity_ids": [target["id"]], "action": "approve"}, token)
        queued = post("/queue", {"opportunity_ids": [target["id"]], "type": "SUBMIT"}, token)
        print(f"queued      : {queued.get('created', 0)} task(s)")

    metrics = get("/dashboard/metrics", token)
    print()
    print("Workspace:")
    print(f"  projects {metrics['projects']} | opportunities {metrics['opportunities']} | approved {metrics['approved']}")
    print(f"  open {args.base}/login  ->  {EMAIL} / {PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
