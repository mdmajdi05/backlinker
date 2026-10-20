"""Manual (human driven) submission adapter.

The adapter never pretends that a submission happened. It prepares a
*submission pack* - the target URL, the anchor text, the description and
the landing page - and hands the task over to an operator. The task stays
in ``WAITING_FOR_USER`` until a human confirms the listing.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.services.adapters.base import (
    RESULT_WAITING_USER,
    BaseAdapter,
    SubmissionContext,
    SubmissionResult,
    register_adapter,
)


def _first(values: list[str] | None) -> str:
    """Return the first non empty entry of *values*."""
    for value in values or []:
        text = str(value or "").strip()
        if text:
            return text
    return ""


class ManualAdapter(BaseAdapter):
    """Prepares a submission pack and hands the work to a human operator."""

    key = "generic_manual"
    name = "Manual assisted submission"
    kind = "MANUAL_ASSISTED"
    description = (
        "Prepares the submission pack (URLs, anchor text, description) and hands the task "
        "to the operator."
    )
    supported_categories: tuple[str, ...] = ()
    supported_methods: tuple[str, ...] = ("MANUAL",)
    supported_environments: tuple[str, ...] = ("CLOUD", "LOCAL")
    required_config: ClassVar[dict[str, Any]] = {}
    required_user_fields: tuple[str, ...] = ("name", "website", "description")
    registration_required = False
    manual_approval_required = True
    automatable = False
    verification_method = "manual"
    retryable_errors: tuple[str, ...] = ()
    restrictions = "Requires a human to complete the submission on the target website."
    success_signals: tuple[str, ...] = ("Operator confirms the listing was created",)
    domains: tuple[str, ...] = ()

    def submit(self, ctx: SubmissionContext) -> SubmissionResult:
        """Prepare the pack and pause the task for a human."""
        pack = build_manual_pack(ctx)
        return SubmissionResult(
            status=RESULT_WAITING_USER,
            message=(
                f"'{ctx.website.domain}' cannot be submitted automatically. "
                "A submission pack was prepared for the operator."
            ),
            expected_destination_url=ctx.landing_page() or None,
            requires_human=True,
            requires_approval=False,
            evidence={"submission_pack": pack, "automated": False},
        )


def build_manual_pack(ctx: SubmissionContext) -> dict[str, Any]:
    """Build everything an operator needs to submit the listing by hand."""
    website = ctx.website
    profile = ctx.profile
    landing_page = ctx.landing_page()
    anchor_text = website.anchor_text or _first(profile.preferred_anchors if profile else None)
    description = website.description or (profile.description if profile else "") or ""
    return {
        "website": website.domain,
        "name": website.name or website.domain,
        "opportunity_url": website.opportunity_url,
        "target_website": landing_page,
        "anchor_text": anchor_text,
        "description": description,
        "category": website.category,
        "submission_method": website.submission_method,
        "contact_email": website.contact_email,
        "adapter": ctx.task.adapter_id or ManualAdapter.key,
        "instructions": (
            "Open the opportunity URL, submit the business details above and mark the task as "
            "completed once the listing is live. The verification engine will then confirm the link."
        ),
    }


register_adapter(ManualAdapter())
