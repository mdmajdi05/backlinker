"""Integration credential storage.

Secrets must be encrypted at rest, never echoed back by the API, and the
metadata needed to use an AI credential (model, base URL) must survive a save.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt
from app.db.models import IntegrationCredential
from app.services.integration_credentials import AI_PROVIDERS

API = "/api/v1"


def test_saving_an_ai_credential_returns_its_model(authenticated_client, db_session) -> None:
    saved = authenticated_client.post(
        f"{API}/integrations/credentials",
        json={
            "provider": "openai",
            "label": "default",
            "secret": "sk-test-secret-value",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["model"] == "gpt-4o-mini"
    assert body["base_url"] == "https://api.openai.com/v1"
    assert body["has_value"] is True
    assert "sk-test-secret-value" not in saved.text

    listed = authenticated_client.get(f"{API}/integrations/credentials")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if item["provider"] == "openai")
    assert row["model"] == "gpt-4o-mini"
    assert row["base_url"] == "https://api.openai.com/v1"

    db_session.rollback()
    stored = db_session.execute(
        select(IntegrationCredential).where(IntegrationCredential.provider == "openai")
    ).scalar_one()
    assert stored.secret_encrypted != "sk-test-secret-value"
    assert (
        decrypt(stored.secret_encrypted, settings.secret_key, associated_data="openai")
        == "sk-test-secret-value"
    )
    assert (stored.meta or {}).get("model") == "gpt-4o-mini"


def test_every_supported_ai_provider_is_known(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/integrations/providers")
    assert response.status_code == 200, response.text
    known = {item["key"] for item in response.json()}
    assert AI_PROVIDERS <= known
    assert "gemini" not in known
    assert "azure" not in known


def test_a_keyless_local_provider_saves_without_a_secret(
    authenticated_client, db_session
) -> None:
    """Ollama / LM Studio / local servers need no API key - only a model."""
    saved = authenticated_client.post(
        f"{API}/integrations/credentials",
        json={
            "provider": "ollama",
            "label": "default",
            "secret": "",
            "model": "llama3.1",
            "base_url": "http://localhost:11434/v1",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["provider"] == "ollama"
    assert body["status"] == "CONFIGURED"
    assert body["model"] == "llama3.1"
    assert body["base_url"] == "http://localhost:11434/v1"
    assert body["has_value"] is False

    providers = authenticated_client.get(f"{API}/integrations/providers")
    assert providers.status_code == 200, providers.text
    ollama = next(item for item in providers.json() if item["key"] == "ollama")
    assert ollama["configured"] is True

    db_session.rollback()
    stored = db_session.execute(
        select(IntegrationCredential).where(IntegrationCredential.provider == "ollama")
    ).scalar_one()
    assert stored.secret_encrypted is None
    assert stored.status == "CONFIGURED"
    assert (stored.meta or {}).get("model") == "llama3.1"


def test_a_keyless_local_provider_requires_a_model(authenticated_client) -> None:
    response = authenticated_client.post(
        f"{API}/integrations/credentials",
        json={"provider": "lmstudio", "label": "default", "secret": ""},
    )
    assert response.status_code == 400, response.text
    assert "model" in response.json()["error"]["message"].lower()


def test_a_key_required_provider_rejects_an_empty_secret(authenticated_client, db_session) -> None:
    response = authenticated_client.post(
        f"{API}/integrations/credentials",
        json={"provider": "openai", "label": "default", "secret": "", "model": "gpt-4o-mini"},
    )
    assert response.status_code == 400, response.text
    message = response.json()["error"]["message"]
    assert "api key" in message.lower()

    db_session.rollback()
    assert (
        db_session.execute(
            select(IntegrationCredential).where(IntegrationCredential.provider == "openai")
        ).scalar_one_or_none()
        is None
    )
