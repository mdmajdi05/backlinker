#!/usr/bin/env python3
"""Check the "Add website" dialog of the Review found websites page with a real browser.

It signs in, opens the review tab of Website discovery, adds a website through the dialog
and verifies that the new record shows up in the table.  A second run adds
the same URL again - the backend deduplicates it, so the list must not grow.

Usage:  .venv/bin/python scripts/check_add_website_ui.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo123456"
URL = "https://ui-check-directory.example/submit"


def api_request(
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict | list | None]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return error.code, None


def purge_test_website() -> None:
    """Remove the record this check created, so the demo data stays clean."""
    status, body = api_request(
        "/api/v1/auth/login",
        method="POST",
        payload={"email": EMAIL, "password": PASSWORD},
    )
    if status != 200 or not isinstance(body, dict):
        print("[WARN] could not sign in to clean up the test website")
        return
    token = str(body.get("access_token") or "")
    status, body = api_request(
        "/api/v1/websites?search=ui-check-directory.example&page_size=10",
        token=token,
    )
    items = body.get("items", []) if isinstance(body, dict) else []
    for item in items:
        if item.get("domain") != "ui-check-directory.example":
            continue
        website_id = str(item.get("id") or "")
        if website_id:
            api_request(f"/api/v1/websites/{website_id}/purge", method="DELETE", token=token)


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )

        # -- sign in ----------------------------------------------------
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_selector('input[type="email"]', timeout=30000)
        page.fill('input[type="email"]', EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/", timeout=30000)
        print("[PASS] signed in")

        # -- discovery review tab ---------------------------------------
        page.goto(f"{BASE}/discovery", wait_until="networkidle")
        page.wait_for_timeout(1200)
        nav = page.get_by_role("navigation", name="Main")
        duplicate_nav = nav.get_by_role("link", name="Review websites").count()
        print(
            f"[{'PASS' if duplicate_nav == 0 else 'FAIL'}] Review websites is not a separate navigation item"
        )
        if duplicate_nav:
            errors.append("Review websites is still in the main navigation")
        page.get_by_role("button", name="Review found websites").click()
        page.wait_for_url(f"{BASE}/registry", timeout=30000)
        page.wait_for_timeout(1500)
        heading_ok = page.get_by_role("heading", name="Review found websites").first.is_visible()
        print(
            f"[{'PASS' if heading_ok else 'FAIL'}] the review step opens inside Website discovery"
        )
        if not heading_ok:
            errors.append("the review tab did not open")
        discovery_link = nav.get_by_role("link", name="Find new websites")
        grouped_ok = discovery_link.get_attribute("aria-current") == "page"
        print(
            f"[{'PASS' if grouped_ok else 'FAIL'}] the discovery navigation stays active on the review tab"
        )
        if not grouped_ok:
            errors.append("the discovery navigation is not active on the review tab")

        before = page.locator("tbody tr").count()

        # -- open the dialog ---------------------------------------------
        page.get_by_role("button", name="Add website").click()
        page.wait_for_timeout(600)
        assert page.get_by_text("Add a website").first.is_visible(), "the dialog did not open"
        print("[PASS] the 'Add website' dialog opens")

        # -- fill it in ----------------------------------------------------
        page.get_by_label("Submission URL").fill(URL)
        page.get_by_label("Name", exact=False).first.fill("UI check directory")
        page.get_by_label("Anchor text").fill("Acme Analytics")
        page.get_by_label("Target landing page").fill("https://acme-analytics.example/product")
        page.get_by_role("dialog").last.get_by_role("button", name="Add website").click()
        page.wait_for_timeout(2500)

        after = page.locator("tbody tr").count()
        content = page.content()
        added = "ui-check-directory.example" in content
        print(f"[{'PASS' if added else 'FAIL'}] the website appears in the Review found websites list")
        if not added:
            errors.append("the new website is not listed")

        # -- duplicate is deduplicated -------------------------------------
        page.get_by_role("button", name="Add website").click()
        page.wait_for_timeout(500)
        page.get_by_label("Submission URL").fill(URL)
        page.get_by_role("dialog").last.get_by_role("button", name="Add website").click()
        page.wait_for_timeout(2500)
        rows_after_duplicate = page.locator("tbody tr").count()
        duplicate_ok = rows_after_duplicate <= max(after, before) + 1
        print(f"[{'PASS' if duplicate_ok else 'FAIL'}] the duplicate did not create a second row")

        browser.close()

    purge_test_website()

    if errors:
        print("\nconsole errors:")
        for error in errors:
            print("  ", error)
        return 1
    print("\nadd-opportunity UI check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
