"""Integration credential endpoints.

Secrets are encrypted at rest (see :mod:`app.core.crypto`) and are never
returned to a client - the API only reports *whether* a credential exists
and a masked hint.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.crypto import decrypt, encrypt, mask
from app.db.models import IntegrationCredential
from app.schemas import ORMModel
from app.services.events import record_event
from app.services.integration_credentials import (
    AI_PROVIDERS,
    credential_is_configured,
    is_keyless_ai_provider,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

#: Providers the platform knows about and what they are used for.
KNOWN_PROVIDERS: dict[str, dict[str, str]] = {
    "brave_search": {
        "name": "Brave Search API",
        "purpose": "Discovery provider - web search results",
        "docs": "https://brave.com/search/api/",
    },
    "serpapi": {
        "name": "SerpAPI",
        "purpose": "Discovery provider - Google / Bing search results",
        "docs": "https://serpapi.com/",
    },
    "openai": {
        "name": "OpenAI (or any OpenAI compatible endpoint)",
        "purpose": "AI assistance - classification, drafts, mapping",
        "docs": "https://platform.openai.com/docs",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "purpose": "AI assistance - classification, drafts, mapping",
        "docs": "https://docs.anthropic.com/",
    },
    "claude": {
        "name": "Anthropic Claude (alias)",
        "purpose": "AI assistance - classification, drafts, mapping",
        "docs": "https://docs.anthropic.com/",
    },
    "openrouter": {
        "name": "OpenRouter",
        "purpose": "AI assistance through an OpenAI compatible gateway",
        "docs": "https://openrouter.ai/docs",
    },
    "groq": {
        "name": "Groq",
        "purpose": "AI assistance through the Groq OpenAI compatible API",
        "docs": "https://console.groq.com/docs",
    },
    "ollama": {
        "name": "Ollama (local models)",
        "purpose": "AI assistance without any external service",
        "docs": "https://ollama.com/",
    },
    "lmstudio": {
        "name": "LM Studio (local models)",
        "purpose": "AI assistance through a local LM Studio server",
        "docs": "https://lmstudio.ai/docs",
    },
    "local": {
        "name": "Local OpenAI compatible server",
        "purpose": "AI assistance through a local OpenAI compatible endpoint",
        "docs": "https://platform.openai.com/docs/api-reference",
    },
    "openai_compatible": {
        "name": "OpenAI compatible endpoint",
        "purpose": "AI assistance through any OpenAI compatible endpoint",
        "docs": "https://platform.openai.com/docs/api-reference",
    },
    "gmail": {
        "name": "Gmail inbox (one-time codes)",
        "purpose": "Account creation - reads the verification code of each sign-up",
        "docs": "https://support.google.com/accounts/answer/185833",
    },
}

# Keep the advertised providers aligned with the providers the AI engine supports.
for _provider_key in AI_PROVIDERS:
    KNOWN_PROVIDERS.setdefault(
        _provider_key,
        {
            "name": _provider_key.replace("_", " ").title(),
            "purpose": "AI assistance",
            "docs": "",
        },
    )


class CredentialOut(ORMModel):
    id: str
    provider: str
    label: str
    status: str
    has_value: bool
    masked_hint: str
    model: str | None = None
    base_url: str | None = None
    updated_at: str


def _to_out(row: IntegrationCredential) -> dict:
    meta = row.meta or {}
    return {
        "id": row.id,
        "provider": row.provider,
        "label": row.label,
        "status": row.status,
        "has_value": bool(row.secret_encrypted),
        "masked_hint": mask(meta.get("hint")),
        "model": meta.get("model"),
        "base_url": meta.get("base_url"),
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


@router.get("/providers")
def list_providers(user: CurrentUser) -> list[dict]:
    """Known providers and whether they are configured."""
    from app.db.session import session_scope

    with session_scope() as db:
        rows = db.execute(select(IntegrationCredential)).scalars().all()
    # A credential counts as configured when its secret is readable, or - for a
    # keyless local AI provider - when it names a model.
    configured = {row.provider for row in rows if credential_is_configured(row)}
    out = []
    for key, meta in KNOWN_PROVIDERS.items():
        out.append(
            {
                "key": key,
                "name": meta["name"],
                "purpose": meta["purpose"],
                "docs": meta["docs"],
                "configured": key in configured,
            }
        )
    return out


@router.get("/credentials")
def list_credentials(db: DbSession, user: CurrentUser) -> list[dict]:
    rows = db.execute(select(IntegrationCredential).order_by(IntegrationCredential.provider)).scalars().all()
    return [_to_out(row) for row in rows]


@router.post("/credentials")
def upsert_credential(payload: dict, db: DbSession, user: CurrentUser) -> dict:
    provider = (payload.get("provider") or "").strip().lower()
    label = (payload.get("label") or "default").strip()
    secret = payload.get("secret") or payload.get("api_key") or ""
    model = str(payload.get("model") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid", "message": "provider is required"},
        )
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unknown_provider", "message": f"Unknown provider: {provider}"},
        )

    row = db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.provider == provider,
            IntegrationCredential.label == label,
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationCredential(provider=provider, label=label, user_id=user.id)
        db.add(row)

    meta = dict(row.meta or {})
    if model:
        meta["model"] = model
    if base_url:
        meta["base_url"] = base_url

    keyless = is_keyless_ai_provider(provider)
    if secret:
        row.secret_encrypted = encrypt(secret, settings.secret_key, associated_data=provider)
        row.status = "CONFIGURED"
        meta["hint"] = mask(secret)
    elif not row.secret_encrypted:
        if keyless and str(meta.get("model") or "").strip():
            # Local AI servers (Ollama, LM Studio, ...) need no API key.
            row.status = "CONFIGURED"
        elif keyless:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid",
                    "message": (
                        f"A model is required for {provider}: local AI providers need no API key."
                    ),
                },
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid",
                    "message": f"An API key (secret) is required for {provider}.",
                },
            )
    row.meta = meta
    db.commit()
    db.refresh(row)
    record_event(
        db,
        "integration.credential_saved",
        f"Credential for {provider} saved",
        metadata={"provider": provider, "label": label},
    )
    return _to_out(row)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: str, db: DbSession, user: CurrentUser) -> None:
    row = db.get(IntegrationCredential, credential_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Credential not found"},
        )
    db.delete(row)
    db.commit()


@router.get("/credentials/{credential_id}/reveal")
def reveal_credential(credential_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Return the decrypted secret - administrators only, never in exports."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Only administrators can reveal a secret"},
        )
    row = db.get(IntegrationCredential, credential_id)
    if row is None or not row.secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Credential not found"},
        )
    return {"provider": row.provider, "secret": decrypt(row.secret_encrypted, settings.secret_key, row.provider)}
