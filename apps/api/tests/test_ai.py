"""AI provider configuration can come from a stored credential."""

from __future__ import annotations

from app.core.config import settings

API = "/api/v1"

_AI_ENV = (
    "AUTOBL_AI_PROVIDER",
    "AUTOBL_AI_BASE_URL",
    "AUTOBL_AI_API_KEY",
    "AUTOBL_AI_MODEL",
)


def _clear_ai_settings(monkeypatch) -> None:
    for name in _AI_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_provider", None)
    monkeypatch.setattr(settings, "ai_base_url", None)
    monkeypatch.setattr(settings, "ai_api_key", None)
    monkeypatch.setattr(settings, "ai_model", None)


def _save_openai_credential(client, model: str = "gpt-4o-mini") -> None:
    response = client.post(
        f"{API}/integrations/credentials",
        json={
            "provider": "openai",
            "label": "default",
            "secret": "sk-stored-secret",
            "model": model,
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert response.status_code == 200, response.text


def test_status_becomes_configured_from_a_stored_credential(
    authenticated_client, monkeypatch
) -> None:
    _clear_ai_settings(monkeypatch)

    before = authenticated_client.get(f"{API}/ai/status")
    assert before.status_code == 200, before.text
    assert before.json() == {"configured": False, "provider": None, "model": None}

    _save_openai_credential(authenticated_client)

    after = authenticated_client.get(f"{API}/ai/status")
    assert after.status_code == 200, after.text
    assert after.json() == {
        "configured": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
    }
    assert "sk-stored-secret" not in after.text


def test_a_complete_environment_configuration_wins(authenticated_client, monkeypatch) -> None:
    _clear_ai_settings(monkeypatch)
    _save_openai_credential(authenticated_client)

    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(settings, "ai_model", "llama-3.1-8b-instant")
    monkeypatch.setattr(settings, "ai_api_key", "gsk-env-secret")
    monkeypatch.setattr(settings, "ai_base_url", None)

    status = authenticated_client.get(f"{API}/ai/status")
    assert status.status_code == 200, status.text
    assert status.json() == {
        "configured": True,
        "provider": "groq",
        "model": "llama-3.1-8b-instant",
    }


def test_an_incomplete_environment_falls_back_to_the_stored_credential(
    authenticated_client, monkeypatch
) -> None:
    _clear_ai_settings(monkeypatch)
    _save_openai_credential(authenticated_client)

    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "ai_model", None)
    monkeypatch.setattr(settings, "ai_api_key", None)

    status = authenticated_client.get(f"{API}/ai/status")
    assert status.status_code == 200, status.text
    assert status.json() == {
        "configured": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
    }


def _save_keyless_credential(
    client,
    provider: str = "ollama",
    model: str = "llama3.1",
) -> None:
    response = client.post(
        f"{API}/integrations/credentials",
        json={
            "provider": provider,
            "label": "default",
            "secret": "",
            "model": model,
        },
    )
    assert response.status_code == 200, response.text


def test_a_keyless_stored_credential_builds_a_provider(
    authenticated_client, monkeypatch
) -> None:
    """A local provider is usable without any API key."""
    _clear_ai_settings(monkeypatch)
    _save_keyless_credential(authenticated_client)

    status = authenticated_client.get(f"{API}/ai/status")
    assert status.status_code == 200, status.text
    assert status.json() == {
        "configured": True,
        "provider": "ollama",
        "model": "llama3.1",
    }

    from app.services.ai import OpenAICompatibleProvider, get_provider

    provider = get_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.is_available() is True
    assert provider.base_url == "http://localhost:11434/v1"


def test_a_keyless_environment_configuration_needs_no_key(
    authenticated_client, monkeypatch
) -> None:
    _clear_ai_settings(monkeypatch)
    monkeypatch.setattr(settings, "ai_provider", "lmstudio")
    monkeypatch.setattr(settings, "ai_model", "qwen2.5-7b-instruct")
    monkeypatch.setattr(settings, "ai_api_key", None)

    status = authenticated_client.get(f"{API}/ai/status")
    assert status.status_code == 200, status.text
    assert status.json() == {
        "configured": True,
        "provider": "lmstudio",
        "model": "qwen2.5-7b-instruct",
    }
