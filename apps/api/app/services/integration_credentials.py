"""Shared access to stored integration credentials.

Credentials are encrypted at rest (see :mod:`app.core.crypto`).  Every service
that needs a stored secret goes through this module so decryption, provider
validation and the "no credential" case behave the same everywhere.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.db.models import IntegrationCredential

log = get_logger(__name__)

#: Providers the AI engine can talk to.  Keep this aligned with
#: :mod:`app.services.ai`.
AI_PROVIDERS = frozenset(
    {
        "openai",
        "openrouter",
        "groq",
        "ollama",
        "lmstudio",
        "local",
        "openai_compatible",
        "anthropic",
        "claude",
    }
)

#: AI providers that run on the local machine and need no API key.  Such a
#: credential is complete as soon as it names a model (the base URL is
#: optional because the AI engine has sensible defaults).
KEYLESS_AI_PROVIDERS = frozenset({"ollama", "lmstudio", "local"})


def is_keyless_ai_provider(provider: str | None) -> bool:
    """Whether ``provider`` is a local AI backend that needs no API key."""
    return (provider or "").strip().lower() in KEYLESS_AI_PROVIDERS


def stored_credential(
    db: Session, provider: str, *, newest: bool = False
) -> IntegrationCredential | None:
    """Return the first (or newest) stored credential of a provider."""
    order = (
        IntegrationCredential.created_at.desc()
        if newest
        else IntegrationCredential.created_at.asc()
    )
    return db.execute(
        select(IntegrationCredential)
        .where(IntegrationCredential.provider == provider)
        .order_by(order, IntegrationCredential.id.asc())
    ).scalars().first()


def newest_ai_credential(db: Session) -> IntegrationCredential | None:
    """Return the newest credential of any AI provider."""
    return db.execute(
        select(IntegrationCredential)
        .where(IntegrationCredential.provider.in_(AI_PROVIDERS))
        .order_by(IntegrationCredential.created_at.desc(), IntegrationCredential.id.asc())
    ).scalars().first()


def credential_secret(credential: IntegrationCredential | None) -> str | None:
    """Decrypt the secret of a credential, or ``None`` when it is unusable."""
    if credential is None or not credential.secret_encrypted:
        return None
    try:
        secret = decrypt(
            credential.secret_encrypted,
            settings.secret_key,
            associated_data=credential.provider,
        )
    except Exception as exc:
        log.warning(
            "stored credential could not be decrypted",
            extra={"extra_fields": {"provider": credential.provider, "error": str(exc)}},
        )
        return None
    return secret or None


def credential_is_configured(credential: IntegrationCredential | None) -> bool:
    """Whether a stored credential is complete enough to be used.

    A readable secret always counts.  Keyless AI providers (Ollama, LM Studio
    and local OpenAI compatible servers) need no secret, so they count as
    configured when they name a model.
    """
    if credential is None:
        return False
    if credential_secret(credential):
        return True
    if is_keyless_ai_provider(credential.provider):
        meta = credential.meta or {}
        return bool(str(meta.get("model") or "").strip())
    return False


def credential_config(credential: IntegrationCredential | None) -> dict[str, Any]:
    """Build the runtime config of a credential (secret + stored metadata)."""
    if credential is None:
        return {}
    config: dict[str, Any] = {}
    secret = credential_secret(credential)
    if secret:
        config["api_key"] = secret
    meta = credential.meta or {}
    model = str(meta.get("model") or "").strip()
    if model:
        config["model"] = model
    base_url = str(meta.get("base_url") or "").strip()
    if base_url:
        config["base_url"] = base_url
    return config


def stored_secret(db: Session, provider: str) -> str | None:
    """Return the decrypted secret of the first credential of a provider."""
    return credential_secret(stored_credential(db, provider))


def stored_config(db: Session, provider: str) -> dict[str, Any]:
    """Return the decrypted config of the first credential of a provider."""
    return credential_config(stored_credential(db, provider))
