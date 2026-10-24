"""Regression tests for the adapter resolution.

The database stores the *row id* of an ``automation_adapters`` row while the
adapter registry is keyed by the adapter *key*.  Both identifiers have to
resolve to the same adapter - otherwise a manually chosen adapter is silently
ignored and an arbitrary one is used instead.
"""

from __future__ import annotations

from app.db.models import AutomationAdapter
from app.services.adapters import base as adapters
from app.services.adapters.base import get_adapter
from app.services.seed import seed_registry
from app.services.submission import resolve_adapter


def _seeded(db_session) -> None:
    """The adapter registry is written by the application lifespan."""
    seed_registry(db_session)
    db_session.commit()


def test_the_adapter_registry_contains_the_expected_adapters() -> None:
    for key in ("generic_manual", "http_form", "playwright_form", "email_outreach", "json_api"):
        assert get_adapter(key) is not None, f"adapter '{key}' is not registered"


def test_an_adapter_resolves_by_key_and_by_row_id(db_session) -> None:
    _seeded(db_session)
    row = db_session.query(AutomationAdapter).filter(AutomationAdapter.key == "playwright_form").one()

    by_key = resolve_adapter(db_session, "playwright_form")
    by_id = resolve_adapter(db_session, row.id)

    assert by_key is not None
    assert by_id is not None
    assert by_key.key == by_id.key == "playwright_form"


def test_an_unknown_adapter_resolves_to_none(db_session) -> None:
    assert resolve_adapter(db_session, "does-not-exist") is None
    assert resolve_adapter(db_session, None) is None
    assert resolve_adapter(db_session, "0123456789abcdef0123456789abcdef") is None


def test_the_adapter_configuration_is_found_for_the_project(db_session, project_id) -> None:
    """The configuration is stored with the row id but looked up by key."""
    from app.db.models import AdapterConfiguration
    from app.services.submission import _adapter_config

    _seeded(db_session)
    row = db_session.query(AutomationAdapter).filter(AutomationAdapter.key == "http_form").one()
    db_session.add(
        AdapterConfiguration(
            adapter_id=row.id,
            project_id=project_id,
            config={"form_url": "https://example.org/form"},
        )
    )
    db_session.commit()

    adapter = get_adapter("http_form")
    assert adapter is not None
    config = _adapter_config(db_session, adapter, project_id)
    assert config.get("form_url") == "https://example.org/form"


def test_the_fallback_adapter_matches_the_submission_method(db_session) -> None:
    """Without an explicit adapter the method of the website decides."""
    from app.db.models import Website

    website = Website(
        name="Example",
        domain="example.org",
        opportunity_url="https://example.org/submit",
        category="BUSINESS_DIRECTORY",
        submission_method="BROWSER_FORM",
    )
    adapter = adapters.adapter_for_website(website)
    assert adapter is not None
    assert "BROWSER_FORM" in adapter.supported_methods


def test_an_unconfigured_generic_adapter_falls_back_to_the_manual_pack(
    db_session, project_id, opportunity_id
) -> None:
    """A directory without configured selectors must wait for the operator.

    The fallback used to pick ``playwright_form`` only because the website
    advertises a ``BROWSER_FORM``.  The adapter then failed with "No form_url
    is configured", so the real manual submission path was never reached.
    """
    from app.db.models import Opportunity, Task, Website
    from app.services.submission import execute_submission

    db_session.rollback()
    opportunity = db_session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    website = db_session.get(Website, opportunity.website_id)
    assert website is not None
    website.submission_method = "BROWSER_FORM"
    task = Task(
        project_id=project_id,
        opportunity_id=opportunity.id,
        website_id=website.id,
        type="SUBMIT",
        status="RUNNING",
        idempotency_key="SUBMIT:unconfigured-adapter",
    )
    db_session.add(task)
    db_session.commit()

    outcome = execute_submission(db_session, task)

    assert outcome.status == "WAITING_FOR_USER"
    assert outcome.requires_human is True
    assert outcome.result["submission_pack"]["opportunity_url"] == website.opportunity_url
    assert outcome.result["submission_pack"]["instructions"]
