#!/usr/bin/env python3
"""Check the project management of the web client with a real browser.

Signs in, renames a project, opens the delete dialog, reads what the dialog
promises and cancels it (the project must still exist).

Usage:  .venv/bin/python scripts/check_project_ui.py
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
EMAIL = "demo@example.com"
PASSWORD = "demo123456"


def main() -> int:
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on(
            "console",
            lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )

        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_selector('input[type="email"]', timeout=30000)
        page.fill('input[type="email"]', EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/", timeout=30000)
        print("[PASS] signed in")

        page.goto(f"{BASE}/projects", wait_until="networkidle")
        page.wait_for_timeout(1500)

        rows = page.locator("tbody tr")
        if rows.count() == 0:
            print("[FAIL] no projects listed")
            failures.append("no projects listed")
        else:
            print(f"[PASS] {rows.count()} projects listed")

        # --- rename ----------------------------------------------------
        original = rows.first.inner_text().splitlines()[0].strip()
        page.get_by_role("button", name="Edit the project").first.click()
        page.wait_for_timeout(800)
        dialog = page.get_by_role("dialog").first
        name_field = dialog.get_by_label("Project name")
        renamed = f"{original} (renamed)"
        name_field.fill(renamed)
        dialog.get_by_role("button", name="Save").click()
        page.wait_for_timeout(2000)
        body = page.content()
        ok = renamed in body
        print(f"[{'PASS' if ok else 'FAIL'}] the project was renamed")
        if not ok:
            failures.append("rename did not work")

        # --- delete dialog ---------------------------------------------
        page.get_by_role("button", name="Delete the project").first.click()
        page.wait_for_timeout(900)
        dialog = page.get_by_role("dialog").first
        text = dialog.inner_text()
        promises = {
            "keeps the websites": "website" in text.lower(),
            "explains the recycle bin": "recycle bin" in text.lower(),
            "mentions that the profile stays": "profile" in text.lower(),
            "mentions the restore": "restore" in text.lower(),
        }
        for label, value in promises.items():
            print(f"[{'PASS' if value else 'FAIL'}] the delete dialog {label}")
            if not value:
                failures.append(f"delete dialog: {label}")

        dialog.get_by_role("button", name="Keep the project").click()
        page.wait_for_timeout(1200)
        still_there = renamed in page.content()
        print(f"[{'PASS' if still_there else 'FAIL'}] cancelling the dialog keeps the project")
        if not still_there:
            failures.append("cancel deleted the project")

        # --- the detail page ---------------------------------------------
        page.goto(f"{BASE}/projects", wait_until="networkidle")
        page.wait_for_timeout(1200)
        links = page.locator("a[href^='/projects/']")
        count = links.count()
        print(f"[{'PASS' if count else 'FAIL'}] the project rows link to their detail page ({count} links)")
        if not count:
            failures.append("no link to the project detail page")
        else:
            href = links.first.get_attribute("href") or ""
            page.goto(f"{BASE}{href}", wait_until="networkidle")
            page.wait_for_timeout(1800)
            detail = page.content()
            has_report = "Report" in detail
            print(f"[{'PASS' if has_report else 'FAIL'}] the detail page shows the report section")
            if not has_report:
                failures.append("the detail page has no report section")

        browser.close()

    if errors:
        print("\nconsole errors:")
        for error in errors[:5]:
            print("  ", error)
    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}")
        return 1
    print("\nproject UI check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
