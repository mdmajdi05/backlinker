#!/usr/bin/env python3
"""Publish the macOS build as a GitHub release.

Uploads the universal disk image and the app bundle as release assets so the
people you share it with can download it directly.

Usage:  GITHUB_TOKEN=ghp_xxx ./scripts/publish_release.py [--tag v1.0.0]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"
REPO = "mdmajdi05/backlinker"


def request(method: str, path: str, token: str, data: bytes | None = None, headers: dict | None = None):
    head = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "autobacklinker-release",
    }
    head.update(headers or {})
    req = urllib.request.Request(
        path if path.startswith("http") else f"{API}{path}",
        data=data,
        headers=head,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=1800) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw.decode("utf-8", "replace")}
        return error.code, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v1.0.0")
    parser.add_argument("--name", default="Auto Backlinker 1.0.0")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    release_dir = ROOT / "release" / "macos"
    dmg = next(iter(sorted(release_dir.glob("*.dmg"))), None)
    if dmg is None:
        print("No .dmg found in release/macos - run the packaging step first", file=sys.stderr)
        return 2

    notes = (ROOT / "release" / "HOW-TO-USE.md").read_text(encoding="utf-8")

    # 1. the release itself
    status, body = request(
        "POST",
        f"/repos/{REPO}/releases",
        token,
        data=json.dumps(
            {
                "tag_name": args.tag,
                "name": args.name,
                "body": notes[:60000],
                "draft": False,
                "prerelease": False,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if status == 422:
        # The release exists already - use it.
        _, releases = request("GET", f"/repos/{REPO}/releases", token)
        existing = next((r for r in releases if r.get("tag_name") == args.tag), None)
        if existing is None:
            print(f"Could not create the release: {status} {body}", file=sys.stderr)
            return 1
        release_id = existing["id"]
        upload_url = existing["upload_url"].split("{")[0]
        print(f"==> release {args.tag} already exists ({release_id})")
    elif status in (200, 201):
        release_id = body["id"]
        upload_url = body["upload_url"].split("{")[0]
        print(f"==> release {args.tag} created ({release_id})")
    else:
        print(f"Could not create the release: {status} {body}", file=sys.stderr)
        return 1

    # 2. the assets (replace an older upload of the same name)
    _, existing_assets = request("GET", f"/repos/{REPO}/releases/{release_id}/assets", token)
    for old in existing_assets:
        request("DELETE", f"/repos/{REPO}/releases/assets/{old['id']}", token)
        print(f"    replaced the older {old['name']}")

    for asset in sorted(release_dir.iterdir()):
        if asset.is_dir() or asset.suffix.lower() not in {".dmg", ".zip", ".txt", ".md"}:
            continue
        size = asset.stat().st_size
        print(f"    uploading {asset.name} ({size / 1048576:.0f} MB) ...", flush=True)
        started = time.time()
        with asset.open("rb") as handle:
            status, body = request(
                "POST",
                f"{upload_url}?name={quote(asset.name)}",
                token,
                data=handle.read(),
                headers={"Content-Type": "application/octet-stream"},
            )
        if status not in (200, 201):
            print(f"    FAILED {asset.name}: {status} {body}", file=sys.stderr)
            continue
        print(f"    done in {time.time() - started:.0f}s")

    print(f"==> https://github.com/{REPO}/releases/tag/{args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
