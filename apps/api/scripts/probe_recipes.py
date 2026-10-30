"""Read the real procedure of every website in the list.

Run this on the machine that holds the database:

    python -m scripts.probe_recipes            # the next 25 websites
    python -m scripts.probe_recipes --all      # every website
    python -m scripts.probe_recipes --domain g2.com --json

For each website it stores the sign-up page, whether Google sign-in is
offered, which verification the mail carries (code / link / none) and the page
where the link is posted.  The account batch and the report read that recipe,
so a site is understood once instead of on every run.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from app.db.models import Website
from app.db.session import init_db, session_scope
from app.services import site_recipe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--all", action="store_true", help="read every website")
    parser.add_argument("--domain", default="", help="one domain only")
    parser.add_argument(
        "--force", action="store_true", help="read again even when a recipe exists"
    )
    parser.add_argument("--json", action="store_true", help="machine readable output")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    init_db()
    with session_scope() as db:
        statement = select(Website).where(Website.status != "DELETED")
        if args.domain:
            statement = statement.where(Website.domain == args.domain.strip().lower())
        websites = list(db.execute(statement.order_by(Website.domain)).scalars())
        if not args.force:
            websites = [
                website
                for website in websites
                if not (
                    isinstance(website.recipe, dict)
                    and website.recipe.get("checked_at")
                )
            ]
        if not args.all:
            websites = websites[: max(1, args.limit)]
        if not websites:
            print("Nothing to read - every website has a procedure already.")
            return 0

        site_recipe.refresh_many(db, websites, workers=max(1, args.workers))
        rows = [
            {
                "domain": website.domain,
                "reachable": bool((website.recipe or {}).get("reachable")),
                "needs_signup": (website.recipe or {}).get("needs_signup"),
                "verification": (website.recipe or {}).get("verification"),
                "google": (website.recipe or {}).get("google"),
                "signup_url": website.signup_url,
                "post_url": website.post_url,
                "steps": (website.recipe or {}).get("steps") or [],
                "error": (website.recipe or {}).get("error"),
            }
            for website in websites
        ]

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    width = max((len(row["domain"]) for row in rows), default=4)
    for row in rows:
        state = "ok" if row["reachable"] else "unreachable"
        signup = "signup" if row["needs_signup"] else "no signup"
        verify = row["verification"] or "unknown"
        print(
            f"{row['domain']:<{width}}  {state:<11} {signup:<10} verify:{verify:<7} "
            f"signup: {row['signup_url'] or '-'}"
        )
        print(f"{'':<{width}}  post: {row['post_url'] or '-'}")
        if row["error"]:
            print(f"{'':<{width}}  error: {row['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
