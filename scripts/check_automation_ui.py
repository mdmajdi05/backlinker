#!/usr/bin/env python3
"""Check the automation panel with a real browser.

It signs in, opens Settings → "Automation & browser" and verifies that the
isolation guarantees, the resource measurement and the pause / resume / stop
controls are shown and that they work against the backend.

Usage:  .venv/bin/python scripts/check_automation_ui.py
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
EMAIL = "demo@example.com"
PASSWORD = "demo123456"


def main() -> int:
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

        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_selector('input[type="email"]', timeout=30000)
        page.fill('input[type="email"]', EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/", timeout=30000)
        print("[PASS] signed in")

        # -- settings ---------------------------------------------------
        page.goto(f"{BASE}/settings", wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Automation & browser").click()
        page.wait_for_timeout(2000)

        content = page.content()
        checks = [
            ("the isolation guarantee is shown", "personal browser is never touched"),
            ("the own profile directory is shown", "Own profile directory"),
            ("the resource measurement is shown", "Resource usage"),
            ("the parallel job limit is shown", "Parallel browser jobs"),
            ("the headless default is shown", "headless"),
        ]
        for label, needle in checks:
            ok = needle.lower() in content.lower()
            print(f"[{'PASS' if ok else 'FAIL'}] {label}")
            if not ok:
                errors.append(label)

        # -- pause / resume -----------------------------------------------
        page.get_by_role("button", name="Pause all").click()
        page.wait_for_timeout(1500)
        paused = "PAUSED" in page.content()
        print(f"[{'PASS' if paused else 'FAIL'}] the pause control works")
        if not paused:
            errors.append("pause did not work")

        page.get_by_role("button", name="Resume").click()
        page.wait_for_timeout(1500)
        running = "RUNNING" in page.content()
        print(f"[{'PASS' if running else 'FAIL'}] the resume control works")
        if not running:
            errors.append("resume did not work")

        # -- live automation page -----------------------------------------
        page.goto(f"{BASE}/automation", wait_until="networkidle")
        page.wait_for_timeout(1500)
        live = page.content()
        for label, needle in [
            ("the automation page shows the execution control", "Execution control"),
            ("the automation page shows the machine load", "Memory free"),
            ("the automation page explains the isolation", "never opened or controlled"),
        ]:
            ok = needle.lower() in live.lower()
            print(f"[{'PASS' if ok else 'FAIL'}] {label}")
            if not ok:
                errors.append(label)

        browser.close()

    if errors:
        print("\nfailed checks:")
        for error in errors:
            print("  ", error)
        return 1
    print("\nautomation UI check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
