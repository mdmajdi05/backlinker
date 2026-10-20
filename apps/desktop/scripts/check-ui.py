#!/usr/bin/env python3
"""Render the desktop frontend in a headless browser and report errors.

This is a *development* helper: it starts the Vite dev server, opens the UI in
headless Chromium and fails when the React application logs an error.

    python scripts/check-ui.py [--url http://127.0.0.1:1420] [--screenshot out.png]
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:1420")
    parser.add_argument("--screenshot", default="")
    parser.add_argument("--wait", type=float, default=4.0)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright")
        print("python -m playwright install chromium")
        return 2

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}")
                if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        response = page.goto(args.url, wait_until="networkidle")
        page.wait_for_timeout(int(args.wait * 1000))
        title = page.title()
        root_children = page.evaluate("document.getElementById('root')?.childElementCount ?? 0")
        body_text = page.evaluate("document.body.innerText.slice(0, 400)")
        if args.screenshot:
            page.screenshot(path=args.screenshot, full_page=True)
        browser.close()

    print(f"url         : {args.url}")
    print(f"status      : {response.status if response else 'n/a'}")
    print(f"title       : {title}")
    print(f"root nodes  : {root_children}")
    print(f"text        : {body_text!r}")
    if errors:
        print("\nERRORS:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("\nno console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
