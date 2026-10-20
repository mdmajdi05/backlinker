"""AI assistance endpoints.

The AI layer is optional.  Every endpoint works without an AI provider: the
service falls back to a deterministic implementation and the response tells the
client whether the content was machine generated (``ai_generated``).
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import CurrentUser
from app.services import ai as ai_service

router = APIRouter(prefix="/ai", tags=["ai"])

ModelT = TypeVar("ModelT", bound=BaseModel)

#: Actions accepted by ``POST /api/v1/ai/{action}``.
ACTIONS = (
    "classify",
    "explain",
    "anchors",
    "outreach",
    "description",
    "map-columns",
    "summarize",
    "recommend",
    "plan",
)


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------


class ClassifyRequest(BaseModel):
    text: str = ""
    url: str = ""
    categories: list[str] = Field(default_factory=list)


class ExplainRequest(BaseModel):
    website: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)


class AnchorsRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    target_url: str | None = None
    count: int = Field(default=5, ge=1, le=20)


class OutreachRequest(BaseModel):
    website: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    anchor_text: str | None = None


class DescriptionRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    category: str | None = None


class MapColumnsRequest(BaseModel):
    headers: list[str] = Field(default_factory=list)


class SummarizeRequest(BaseModel):
    errors: list[Any] = Field(default_factory=list)


class RecommendRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class PlanRequest(BaseModel):
    project_summary: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/status")
def ai_status(user: CurrentUser) -> dict[str, Any]:
    """Report whether an AI provider is configured (never exposes secrets)."""
    return ai_service.provider_status()


@router.post("/{action}")
def run_ai_action(
    action: str,
    user: CurrentUser,
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    """Run one AI helper.

    ``action`` is one of :data:`ACTIONS`.  The request body depends on the
    action - see the individual models above.
    """
    if action not in ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unknown_action",
                "message": f"Unknown AI action: {action}",
                "details": {"supported": list(ACTIONS)},
            },
        )

    body = payload or {}

    if action == "classify":
        request = _validate(ClassifyRequest, body)
        result = ai_service.classify_opportunity(request.text, request.url, request.categories)
        return {"action": action, **result}

    if action == "explain":
        request = _validate(ExplainRequest, body)
        result = ai_service.explain_relevance(request.website, request.profile)
        return {"action": action, "text": str(result), "ai_generated": result.ai_generated}

    if action == "anchors":
        request = _validate(AnchorsRequest, body)
        result = ai_service.suggest_anchors(request.profile, request.target_url, request.count)
        return {"action": action, "anchors": list(result), "ai_generated": result.ai_generated}

    if action == "outreach":
        request = _validate(OutreachRequest, body)
        result = ai_service.draft_outreach_email(request.website, request.profile, request.anchor_text)
        return {"action": action, **result}

    if action == "description":
        request = _validate(DescriptionRequest, body)
        result = ai_service.draft_directory_description(request.profile, request.category)
        return {"action": action, "description": str(result), "ai_generated": result.ai_generated}

    if action == "map-columns":
        request = _validate(MapColumnsRequest, body)
        mapping = ai_service.map_columns(request.headers)
        generated = any(bool(item.get("ai_generated")) for item in mapping)
        return {"action": action, "mapping": mapping, "ai_generated": generated}

    if action == "summarize":
        request = _validate(SummarizeRequest, body)
        result = ai_service.summarize_errors(request.errors)
        return {"action": action, "summary": str(result), "ai_generated": result.ai_generated}

    if action == "recommend":
        request = _validate(RecommendRequest, body)
        result = ai_service.recommend_next_actions(request.context)
        return {"action": action, "actions": list(result), "ai_generated": result.ai_generated}

    if action == "plan":
        request = _validate(PlanRequest, body)
        result = ai_service.plan_automation(request.project_summary)
        return {"action": action, **result}

    raise HTTPException(  # pragma: no cover - unreachable, ACTIONS is exhaustive
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "unknown_action", "message": f"Unknown AI action: {action}"},
    )


def _validate(model: type[ModelT], body: dict[str, Any]) -> ModelT:
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_request",
                "message": "The request payload is invalid",
                "details": exc.errors(),
            },
        ) from exc
