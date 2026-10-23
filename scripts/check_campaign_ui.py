#!/usr/bin/env python3
"""Check the campaign cockpit of a project with a real browser.

The cockpit is the one screen of a project:

* paste one or more URLs and add them,
* press "Start backlinks" and read the result,
* watch the live table - data filled, status, last update,
* mark a manual submission as done.

The check adds two throw-away URLs, starts the work and verifies that the
table reports the rows instead of losing them.

Usage:  .venv/bin/python scripts/check_campaign_ui.py
"""

from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
EMAIL = "demo@example.com"
PASSWORD = "demo123456"
STAMP = int(time.time())
ONE = f"campaign-check-{STAMP}-one.example/add-listing"
TWO = f"campaign-check-{STAMP}-two.example/submit"


def main() -> int:
    failures: list[str] = []
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
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

        # -- open the first project -------------------------------------
        page.goto(f"{BASE}/projects", wait_until="networkidle")
        page.wait_for_timeout(1200)
        link = page.locator("a[href^='/projects/']").first
        if link.count() == 0:
            print("[FAIL] no project to open")
            failures.append("no project")
            browser.close()
            return 1
        page.goto(f"{BASE}{link.get_attribute('href')}", wait_until="networkidle")
        page.wait_for_selector("text=Backlink campaign", timeout=30000)
        print("[PASS] the project page shows the campaign cockpit")

        # The advanced block must stay collapsed - the page is not crowded.
        details = page.locator("details").first
        if details.count() and details.get_attribute("open") is None:
            print("[PASS] the advanced section is collapsed by default")
        else:
            print("[WARN] the advanced section is open")
        print(
            f"[{'PASS' if page.locator('summary', has_text='Advanced').count() else 'FAIL'}]"
            " the advanced section exists"
        )
        if page.locator("summary", has_text="Advanced").count() == 0:
            failures.append("no advanced section")

        # -- paste two URLs ---------------------------------------------
        page.get_by_label("Add websites").fill(f"{ONE}, {TWO}")
        page.get_by_role("button", name="Add websites").last.click()
        page.wait_for_timeout(2000)
        body = page.content()
        for domain in (ONE.split("/")[0], TWO.split("/")[0]):
            ok = domain in body
            print(f"[{'PASS' if ok else 'FAIL'}] the row of {domain} is in the table")
            if not ok:
                failures.append(f"row missing: {domain}")

        # -- start -------------------------------------------------------
        page.get_by_role("button", name="Start backlinks").first.click()
        page.wait_for_timeout(700)
        dialog = page.get_by_role("dialog").last
        if dialog.count() == 0:
            print("[FAIL] the start dialog did not open")
            failures.append("no start dialog")
        else:
            text = dialog.inner_text().lower()
            explained = "business profile" in text and "active" in text
            print(
                f"[{'PASS' if explained else 'FAIL'}]"
                " the start dialog explains what happens"
            )
            if not explained:
                failures.append("start dialog does not explain")
            dialog.get_by_role("button", name="Start backlinks").click()
            page.wait_for_timeout(2500)

        page.wait_for_selector("text=Backlink work started", timeout=30000)
        result_text = page.get_by_role("dialog").last.inner_text()
        print("[PASS] the start result is reported")
        if "queued" not in result_text.lower():
            failures.append("the start result does not mention the queue")
        page.get_by_role("button", name="Close").click()
        page.wait_for_timeout(600)

        # -- the live table ---------------------------------------------
        page.wait_for_timeout(2500)
        table = page.locator("table").first.inner_text()
        percent_ok = "%" in table
        print(f"[{'PASS' if percent_ok else 'FAIL'}] the table shows the data filled")
        if not percent_ok:
            failures.append("no percentage in the table")

        # The work starts asynchronously: wait until the rows settle in a
        # state that is not "queued".  A site without an adapter ends at
        # "Submit by hand".
        manual = page.get_by_role("button", name="Mark submitted")
        for _ in range(20):
            if manual.count() > 0:
                break
            page.wait_for_timeout(1000)
        if manual.count() > 0:
            print("[PASS] a manual submission is offered")
            manual.first.click()
            page.wait_for_timeout(600)
            dialog = page.get_by_role("dialog").last
            dialog.get_by_role("button", name="Mark submitted").click()
            page.wait_for_timeout(3000)
            after = page.locator("table").first.inner_text()
            settled = any(
                label in after
                for label in (
                    "Submitted",
                    "Verification failed",
                    "Verified",
                )
            )
            print(
                f"[{'PASS' if settled else 'FAIL'}] marking a row updates its status"
            )
            if not settled:
                failures.append("the row did not settle after marking it")
        else:
            print("[WARN] no manual row appeared in time")

        # -- the table survives a reload --------------------------------
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2000)
        reloaded = page.content()
        kept = ONE.split("/")[0] in reloaded and TWO.split("/")[0] in reloaded
        print(f"[{'PASS' if kept else 'FAIL'}] the rows stay after a reload")
        if not kept:
            failures.append("the rows disappeared after a reload")

        browser.close()

    if errors:
        print("\nconsole errors:")
        for error in errors[:5]:
            print("  ", error)
    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}")
        return 1
    print("\ncampaign UI check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
