"""Adapter tests (skipped until the adapter implementations exist).

The adapter registry is the contract between the queue and the site specific
submission logic.  The tests exercise the real registry and the real
``ManualAdapter`` - no adapter implementation is mocked.
"""

from __future__ import annotations

import pytest

from app.db.models import Opportunity, Project
from tests.conftest import API

adapters = pytest.importorskip(
    "app.services.adapters",
    reason="the adapter implementations (app.services.adapters.impl) are not available yet",
    exc_type=ImportError,
)

SEEDED_ADAPTER_KEYS = {
    "generic_manual",
    "http_form",
    "playwright_form",
    "email_outreach",
    "json_api",
}


def test_the_registry_contains_the_seeded_adapters() -> None:
    registered = {adapter.key for adapter in adapters.all_adapters()}

    assert SEEDED_ADAPTER_KEYS.issubset(registered)
    for key in SEEDED_ADAPTER_KEYS:
        adapter = adapters.get_adapter(key)
        assert adapter is not None
        assert adapter.name
        assert adapter.supported_environments


def test_an_unknown_adapter_key_is_not_registered() -> None:
    assert adapters.get_adapter("does-not-exist") is None
    assert adapters.get_adapter(None) is None


def test_the_api_lists_the_adapters(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/adapters")

    assert response.status_code == 200, response.text
    keys = {adapter["key"] for adapter in response.json()}
    assert SEEDED_ADAPTER_KEYS.issubset(keys)


def test_the_manual_adapter_prepares_a_submission_pack(
    authenticated_client, project_id, opportunity_id, db_session
) -> None:
    from app.services.adapters.base import SubmissionContext

    adapter = adapters.get_adapter("generic_manual")
    assert adapter is not None
    assert adapter.automatable is False
    assert adapter.manual_approval_required is True

    db_session.rollback()
    website = (
        db_session.query(Opportunity)
        .filter(Opportunity.id == opportunity_id)
        .one()
        .website
    )
    project = db_session.get(Project, project_id)
    opportunity = db_session.get(Opportunity, opportunity_id)

    class _Task:
        id = "task-1"
        adapter_id = None

    context = SubmissionContext(
        db=db_session,
        task=_Task(),
        website=website,
        opportunity=opportunity,
        project=project,
        profile=None,
    )

    result = adapter.submit(context)

    assert result.status == adapters.RESULT_WAITING_USER
    assert result.requires_human is True
    assert result.succeeded is False
    pack = result.evidence["submission_pack"]
    assert pack["website"] == website.domain
    assert pack["opportunity_url"] == website.opportunity_url
    assert pack["instructions"]
