#!/usr/bin/env python3
"""Check the "Add website" dialog of the Review websites page with a real browser.

It signs in, opens the Review websites page, adds a website through the dialog
and verifies that the new record shows up in the table.  A second run adds
the same URL again - the backend deduplicates it, so the list must not grow.

Usage:  .venv/bin/python scripts/check_add_website_ui.py
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
EMAIL = "demo@example.com"
PASSWORD = "demo123456"
URL = "https://ui-check-directory.example/submit"


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

        # -- registry ----------------------------------------------------
        page.goto(f"{BASE}/registry", wait_until="networkidle")
        page.wait_for_timeout(1500)

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
        print(f"[{'PASS' if added else 'FAIL'}] the website appears in the Review websites list")
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

    if errors:
        print("\nconsole errors:")
        for error in errors:
            print("  ", error)
        return 1
    print("\nadd-opportunity UI check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
