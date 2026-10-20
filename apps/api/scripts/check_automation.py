"""Self check of the automation layer.

The script builds a temporary SQLite database, seeds the registry, runs the
``manual_seed`` provider against two example URLs, scores the results with
the scoring engine and prints the provider / adapter registry.

It never submits anything and it never fills a form. The only outbound
request it may perform is a single optional reachability probe of
``https://example.com`` - it is skipped automatically when the network is
not available.

Run it with::

    cd apps/api && ../../.venv/bin/python scripts/check_automation.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import (
    AutomationAdapter,
    BusinessProfile,
    DiscoveryRun,
    DiscoverySource,
    Opportunity,
    Project,
    ProjectSettings,
    Task,
    Website,
)
from app.services.adapters import all_adapters
from app.services.discovery import load_providers
from app.services.discovery.base import DiscoveryCriteria, all_providers, get_provider
from app.services.discovery.runner import run_discovery_task
from app.services.scoring import score_opportunity
from app.services.seed import seed_registry

EXAMPLE_URLS = [
    "https://example.com/add-your-business",
    "https://example.org/write-for-us",
]


def build_database() -> tuple[Session, str]:
    """Create a temporary SQLite database with the full schema."""
    directory = tempfile.mkdtemp(prefix="autobacklinker-check-")
    url = f"sqlite:///{Path(directory) / 'check.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory(), url


def seed_project(db: Session) -> Project:
    """Create a business profile and a project for the check."""
    profile = BusinessProfile(
        name="Example Studio",
        primary_website="https://example.com",
        description="A small studio that builds documentation tooling for product teams.",
        industry="Software",
        niche="developer tools",
        keywords=["developer tools", "documentation", "product teams"],
        preferred_anchors=["developer documentation"],
        target_countries=["US"],
        preferred_language="en",
    )
    db.add(profile)
    db.flush()
    project = Project(
        name="Example Studio - backlinks",
        slug="example-studio-backlinks",
        target_website="https://example.com/docs",
        business_profile_id=profile.id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectSettings(project_id=project.id, verify_interval_hours=168))
    db.commit()
    return project


def print_registry(db: Session) -> None:
    """Print the discovery providers and the submission adapters."""
    print("== discovery providers ==")
    for provider in all_providers():
        available, reason = provider.available({})
        source = db.execute(
            select(DiscoverySource).where(DiscoverySource.key == provider.key)
        ).scalar_one_or_none()
        print(
            f"  {provider.key:<16} available={available!s:<5} credentials={provider.requires_credentials!s:<5} "
            f"seeded={source is not None} {reason}"
        )
    print("== submission adapters ==")
    for adapter in all_adapters():
        row = db.execute(
            select(AutomationAdapter).where(AutomationAdapter.key == adapter.key)
        ).scalar_one_or_none()
        print(
            f"  {adapter.key:<16} automatable={adapter.automatable!s:<5} seeded={row is not None} "
            f"method={','.join(adapter.supported_methods)}"
        )


def print_score(title: str, breakdown: dict) -> None:
    """Print a score breakdown in a readable way."""
    print(f"-- {title} --")
    for key in (
        "topical_relevance",
        "site_quality",
        "editorial_relevance",
        "links_allowed",
        "documented_submission",
        "effort",
        "business_value",
        "relationship",
        "spam_penalty",
        "total",
    ):
        print(f"  {key:<24} {breakdown[key]}")
    print("  reasons:")
    for reason in breakdown["reasons"]:
        print(f"    - {reason}")
    print(f"  unavailable_metrics: {', '.join(breakdown['unavailable_metrics'])}")


def optional_probe() -> None:
    """A single reachability probe of a public example URL."""
    from app.core.net import safe_get

    print("== optional reachability probe ==")
    try:
        response = safe_get("https://example.com", timeout=8.0)
    except Exception as exc:
        print(f"  skipped: {type(exc).__name__}: {exc}")
        return
    if response.error:
        print(f"  skipped: {response.error}")
        return
    print(f"  https://example.com -> HTTP {response.status_code} in {response.elapsed_ms} ms")


def main() -> int:
    """Run the self check."""
    db, url = build_database()
    print(f"temporary database: {url}")
    try:
        seed_registry(db)
        load_providers()
        project = seed_project(db)

        provider = get_provider("manual_seed")
        if provider is None:
            print("the manual_seed provider is not registered")
            return 1
        available, reason = provider.available({})
        print(f"manual_seed available: {available} {reason}")

        criteria = DiscoveryCriteria(
            query="add your business",
            keywords=["developer tools", "documentation"],
            category="BUSINESS_DIRECTORY",
            limit=10,
            seeds=list(EXAMPLE_URLS),
            config={"fetch_content": False},
            project_id=project.id,
        )
        sites = provider.discover(criteria)
        print(f"manual_seed discovered {len(sites)} site(s)")

        profile = db.get(BusinessProfile, project.business_profile_id)
        for site in sites:
            breakdown = score_opportunity(
                website_url=site.url,
                title=site.name,
                description=site.description or "",
                text="",
                category=site.category,
                domain=site.domain,
                profile=profile,
                profile_keywords=["developer tools", "documentation"],
                submission_method=site.submission_method,
                registration_required=site.registration_required,
                requires_approval=site.requires_approval,
            )
            print_score(f"{site.domain} ({site.source})", breakdown)

        # The discovery runner stores the candidates in the database.
        run = DiscoveryRun(
            project_id=project.id,
            provider="manual_seed",
            status="PENDING",
            query="add your business",
            keywords=["developer tools"],
            config={"fetch_content": False},
            requested_limit=10,
        )
        db.add(run)
        db.flush()
        task = Task(
            project_id=project.id,
            type="DISCOVER",
            status="RUNNING",
            idempotency_key=f"DISCOVER:check:{run.id}",
            payload={
                "run_id": run.id,
                "provider": "manual_seed",
                "criteria": {
                    "query": "add your business",
                    "keywords": ["developer tools"],
                    "category": "BUSINESS_DIRECTORY",
                    "limit": 10,
                    "seeds": list(EXAMPLE_URLS),
                    "config": {"fetch_content": False},
                },
            },
        )
        db.add(task)
        db.commit()

        outcome = run_discovery_task(db, task)
        db.refresh(run)
        websites = db.execute(select(Website)).scalars().all()
        opportunities = db.execute(select(Opportunity)).scalars().all()
        print("== discovery runner ==")
        print(f"  outcome: {outcome.status} - {outcome.message}")
        print(f"  run counters: {json.dumps(outcome.result, sort_keys=True)}")
        print(f"  run status: {run.status} (new={run.new_count}, duplicate={run.duplicate_count}, rejected={run.rejected_count})")
        print(f"  websites: {len(websites)}, opportunities: {len(opportunities)}")
        for website in websites:
            print(
                f"    - {website.domain} score={website.score} source={website.discovery_source}"
                f" breakdown_keys={sorted((website.score_breakdown or {}).keys())}"
            )

        # A second run has to detect the duplicates.
        duplicate_task = Task(
            project_id=project.id,
            type="DISCOVER",
            status="RUNNING",
            idempotency_key=f"DISCOVER:check:duplicate:{run.id}",
            payload={
                "run_id": run.id,
                "provider": "manual_seed",
                "criteria": {
                    "limit": 10,
                    "seeds": list(EXAMPLE_URLS),
                    "config": {"fetch_content": False},
                },
            },
        )
        db.add(duplicate_task)
        db.commit()
        second = run_discovery_task(db, duplicate_task)
        print(f"  second run: {second.status} - {json.dumps(second.result, sort_keys=True)}")

        print_registry(db)
        optional_probe()
        print("check finished successfully")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
