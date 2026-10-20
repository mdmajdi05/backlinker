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
    "openrouter": {
        "name": "OpenRouter",
        "purpose": "AI assistance through an OpenAI compatible gateway",
        "docs": "https://openrouter.ai/docs",
    },
    "ollama": {
        "name": "Ollama (local models)",
        "purpose": "AI assistance without any external service",
        "docs": "https://ollama.com/",
    },
}


class CredentialOut(ORMModel):
    id: str
    provider: str
    label: str
    status: str
    has_value: bool
    masked_hint: str
    updated_at: str


def _to_out(row: IntegrationCredential) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "label": row.label,
        "status": row.status,
        "has_value": bool(row.secret_encrypted),
        "masked_hint": mask((row.meta or {}).get("hint")),
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


@router.get("/providers")
def list_providers(user: CurrentUser) -> list[dict]:
    """Known providers and whether they are configured."""
    from app.db.session import session_scope

    with session_scope() as db:
        rows = db.execute(select(IntegrationCredential)).scalars().all()
    configured = {row.provider for row in rows if row.secret_encrypted}
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

    if secret:
        row.secret_encrypted = encrypt(secret, settings.secret_key, associated_data=provider)
        row.status = "CONFIGURED"
        row.meta = {**(row.meta or {}), "hint": mask(secret)}
    elif row.secret_encrypted:
        # Keep the existing secret but let the user change the metadata.
        row.meta = {**(row.meta or {}), "hint": mask((row.meta or {}).get("hint", ""))}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid", "message": "A secret is required for a new credential"},
        )
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
