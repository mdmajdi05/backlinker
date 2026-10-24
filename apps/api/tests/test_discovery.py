"""Discovery credentials are decrypted before they are used."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.crypto import encrypt
from app.db.models import DiscoveryRun, IntegrationCredential, Task
from app.services import queue as queue_service
from app.services.discovery import load_providers
from app.services.discovery.base import get_provider
from app.services.discovery.runner import run_discovery_task

API = "/api/v1"

_DISCOVERY_ENV = ("AUTOBL_BRAVE_SEARCH_API_KEY", "BRAVE_SEARCH_API_KEY")


def _clear_discovery_env(monkeypatch) -> None:
    for name in _DISCOVERY_ENV:
        monkeypatch.delenv(name, raising=False)


def _save_brave_credential(client, secret: str) -> None:
    response = client.post(
        f"{API}/integrations/credentials",
        json={"provider": "brave_search", "label": "default", "secret": secret},
    )
    assert response.status_code == 200, response.text


def test_a_stored_key_makes_the_provider_available_without_being_persisted(
    authenticated_client, project_id, db_session, monkeypatch
) -> None:
    _clear_discovery_env(monkeypatch)

    before = authenticated_client.get(f"{API}/discovery/providers")
    assert before.status_code == 200, before.text
    brave = next(item for item in before.json() if item["key"] == "brave_search")
    assert brave["available"] is False

    _save_brave_credential(authenticated_client, "brave-route-secret")

    after = authenticated_client.get(f"{API}/discovery/providers")
    brave = next(item for item in after.json() if item["key"] == "brave_search")
    assert brave["available"] is True

    started = authenticated_client.post(
        f"{API}/discovery/runs",
        json={
            "project_id": project_id,
            "provider": "brave_search",
            "query": "seo",
            "limit": 3,
            "config": {"search_lang": "en"},
        },
    )
    assert started.status_code == 202, started.text

    db_session.rollback()
    run = db_session.get(DiscoveryRun, started.json()["id"])
    assert run is not None
    assert run.config == {"search_lang": "en"}
    assert "brave-route-secret" not in json.dumps(run.config)

    task = db_session.execute(select(Task).where(Task.type == "DISCOVER")).scalars().first()
    assert task is not None
    assert task.payload["criteria"]["config"] == {"search_lang": "en"}
    assert "brave-route-secret" not in json.dumps(task.payload)

    # The stored credential is decrypted when the task executes, even though
    # neither the run row nor the payload contains it.
    load_providers()
    provider = get_provider("brave_search")
    assert provider is not None
    seen: dict = {}

    def fake_discover(criteria):
        seen["config"] = dict(criteria.config)
        return []

    monkeypatch.setattr(provider, "discover", fake_discover)
    outcome = run_discovery_task(db_session, task)
    assert outcome.status == "COMPLETED", outcome.error
    assert seen["config"]["api_key"] == "brave-route-secret"


@pytest.mark.parametrize("secret_key", ["api_key", "token", "subscription_token"])
def test_a_per_run_secret_is_rejected_instead_of_being_stored(
    authenticated_client, project_id, db_session, monkeypatch, secret_key: str
) -> None:
    _clear_discovery_env(monkeypatch)

    started = authenticated_client.post(
        f"{API}/discovery/runs",
        json={
            "project_id": project_id,
            "provider": "brave_search",
            "query": "seo",
            "config": {secret_key: "inline-route-secret"},
        },
    )
    assert started.status_code == 400, started.text
    error = started.json()["error"]
    assert error["code"] == "provider_secret_in_request"
    assert "API keys & integrations" in error["message"]

    db_session.rollback()
    assert db_session.execute(select(func.count()).select_from(DiscoveryRun)).scalar() == 0
    assert db_session.execute(select(func.count()).select_from(Task)).scalar() == 0


def test_the_runner_decrypts_a_stored_key(db_session, project_id, monkeypatch) -> None:
    _clear_discovery_env(monkeypatch)
    load_providers()
    provider = get_provider("brave_search")
    assert provider is not None

    db_session.add(
        IntegrationCredential(
            provider="brave_search",
            label="default",
            secret_encrypted=encrypt(
                "brave-runner-secret", settings.secret_key, associated_data="brave_search"
            ),
        )
    )
    run = DiscoveryRun(
        project_id=project_id,
        provider="brave_search",
        status="PENDING",
        query="seo",
        requested_limit=3,
        config={},
    )
    db_session.add(run)
    db_session.commit()

    task, _created = queue_service.enqueue(
        db_session,
        task_type="DISCOVER",
        project_id=project_id,
        payload={
            "run_id": run.id,
            "provider": "brave_search",
            "criteria": {"query": "seo", "limit": 3},
        },
        idempotency_key="discover-runner-secret",
    )

    seen: dict = {}

    def fake_discover(criteria):
        seen["config"] = dict(criteria.config)
        return []

    monkeypatch.setattr(provider, "discover", fake_discover)

    outcome = run_discovery_task(db_session, task)
    assert outcome.status == "COMPLETED", outcome.error
    assert seen["config"]["api_key"] == "brave-runner-secret"
    assert "v1:" not in seen["config"]["api_key"]


def test_an_unreadable_key_is_never_reported_as_available(
    authenticated_client, project_id, db_session, monkeypatch
) -> None:
    _clear_discovery_env(monkeypatch)
    db_session.add(
        IntegrationCredential(
            provider="brave_search",
            label="default",
            secret_encrypted="v1:not-a-valid-payload",
        )
    )
    db_session.commit()

    providers = authenticated_client.get(f"{API}/discovery/providers")
    brave = next(item for item in providers.json() if item["key"] == "brave_search")
    assert brave["available"] is False

    started = authenticated_client.post(
        f"{API}/discovery/runs",
        json={"project_id": project_id, "provider": "brave_search", "query": "seo"},
    )
    assert started.status_code == 400, started.text
    assert started.json()["error"]["code"] == "provider_unavailable"
