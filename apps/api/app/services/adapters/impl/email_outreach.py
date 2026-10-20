"""Email outreach adapter.

The adapter prepares a *draft* - it never sends an email. Sending requires
an explicit human approval, therefore the result is
``WAITING_FOR_APPROVAL``.

The draft only contains facts of the business profile (name, description,
landing page, anchor text, author bio). It never invents testimonials,
reviews, customer names or performance claims - those would be fabricated
statements sent to a third party.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.db.models import SubmissionEvidence
from app.services.adapters.base import (
    RESULT_WAITING_APPROVAL,
    BaseAdapter,
    SubmissionContext,
    SubmissionResult,
    register_adapter,
)
from app.services.adapters.impl import render_template, submission_values

_GREETINGS = {
    "formal": "Dear {{recipient}},",
    "casual": "Hi {{recipient}},",
    "default": "Hello {{recipient}},",
}


class EmailOutreachAdapter(BaseAdapter):
    """Drafts a personalised outreach email for a human to review and send."""

    key = "email_outreach"
    name = "Email outreach adapter"
    kind = "EMAIL_OUTREACH"
    description = (
        "Drafts a personalised outreach email. Sending requires explicit operator confirmation."
    )
    supported_categories: tuple[str, ...] = ()
    supported_methods: tuple[str, ...] = ("EMAIL_OUTREACH",)
    supported_environments: tuple[str, ...] = ("CLOUD", "LOCAL")
    required_config: ClassVar[dict[str, Any]] = {
        "contact_email": "string - recipient address",
        "tone": "string - optional tone instruction for the draft",
    }
    required_user_fields: tuple[str, ...] = ("name", "website", "description", "author_bio")
    registration_required = False
    manual_approval_required = True
    automatable = True
    verification_method = "manual"
    retryable_errors: tuple[str, ...] = ()
    restrictions = "Drafts are never sent automatically without operator approval."
    success_signals: tuple[str, ...] = ("Draft created and stored on the task",)
    domains: tuple[str, ...] = ()

    def submit(self, ctx: SubmissionContext) -> SubmissionResult:
        """Build the outreach draft and ask for approval."""
        config = ctx.adapter_config or {}
        values = submission_values(ctx)
        profile = ctx.profile
        website = ctx.website

        recipient = str(config.get("contact_email") or website.contact_email or "").strip()
        recipient_name = str(config.get("recipient_name") or "").strip()
        tone = str(config.get("tone") or "default").strip().lower()
        if tone not in _GREETINGS:
            tone = "default"

        landing_page = values.get("landing_page") or values.get("website")
        anchor_text = values.get("anchor_text") or values.get("name")
        description = values.get("description") or ""
        sender_name = values.get("name") or ""
        keywords = _keywords(ctx)

        subject = _subject(website.name or website.domain, values.get("niche") or keywords)
        body = _body(
            greeting=render_template(
                _GREETINGS[tone], {"recipient": recipient_name or "there"}
            ),
            domain=website.domain,
            landing_page=landing_page,
            description=description,
            anchor_text=anchor_text,
            sender_name=sender_name,
            sender_website=values.get("website"),
            sender_email=values.get("email"),
            keywords=keywords,
            author_bio=_first(profile.author_bios if profile else None),
        )

        draft = {
            "to": recipient,
            "recipient_name": recipient_name,
            "subject": subject,
            "body": body,
            "anchor_text": anchor_text,
            "landing_page": landing_page,
            "tone": tone,
            "claims_policy": (
                "The draft only contains facts of the business profile. No testimonial, review, "
                "customer name or performance claim was added."
            ),
        }
        evidence = {
            "email_draft": draft,
            "recipient": recipient,
            "recipient_missing": not recipient,
            "requires_human_send": True,
        }
        self._store_draft(ctx, draft)

        message = "An outreach draft was prepared. Review it and send the email yourself."
        if not recipient:
            message = (
                "An outreach draft was prepared but no recipient address is known. "
                "Add a contact address and send the email yourself."
            )
        return SubmissionResult(
            status=RESULT_WAITING_APPROVAL,
            message=message,
            expected_destination_url=landing_page or None,
            requires_human=True,
            requires_approval=True,
            evidence=evidence,
        )

    def _store_draft(self, ctx: SubmissionContext, draft: dict[str, Any]) -> None:
        """Persist the draft so the operator can find it again."""
        try:
            ctx.db.add(
                SubmissionEvidence(
                    task_id=ctx.task.id,
                    opportunity_id=ctx.task.opportunity_id,
                    kind="email_draft",
                    excerpt=str(draft.get("subject") or "")[:500],
                    metadata=draft,
                )
            )
            ctx.db.commit()
        except Exception:
            ctx.db.rollback()


def _subject(site_name: str, topic: str) -> str:
    """Build a short, honest subject line."""
    if topic:
        return f"A suggestion for {site_name} ({topic})"
    return f"A suggestion for {site_name}"


def _body(
    *,
    greeting: str,
    domain: str,
    landing_page: str,
    description: str,
    anchor_text: str,
    sender_name: str,
    sender_website: str,
    sender_email: str,
    keywords: str,
    author_bio: str,
) -> str:
    """Compose the body of the outreach email."""
    lines: list[str] = [greeting, ""]
    if keywords:
        lines.append(
            f"I found {domain} while looking for {keywords} and thought the page below could be a "
            "useful addition to the listings you publish."
        )
    else:
        lines.append(
            f"I found {domain} and thought the page below could be a useful addition to the "
            "listings you publish."
        )
    lines.append("")
    if landing_page:
        lines.append(f"{landing_page}")
    if description:
        lines.append(f"- {description}")
    lines.append("")
    lines.append(
        f"If it fits your guidelines, the anchor text could be \"{anchor_text}\". "
        "Please use the link exactly as it is if you decide to add it."
    )
    lines.append("")
    lines.append(
        "If the page is not a fit for your audience, just let me know - I will not follow up."
    )
    lines.append("")
    lines.append("Best regards,")
    if sender_name:
        lines.append(sender_name)
    if sender_website:
        lines.append(sender_website)
    if sender_email:
        lines.append(sender_email)
    if author_bio:
        lines.append("")
        lines.append(author_bio)
    return "\n".join(lines).strip()


def _keywords(ctx: SubmissionContext) -> str:
    """A short keyword phrase built from the business profile."""
    profile = ctx.profile
    if profile is None:
        return ""
    parts = [part for part in (profile.niche, profile.industry) if part]
    if parts:
        return " and ".join(parts)
    keywords = [str(item) for item in (profile.keywords or [])][:3]
    return ", ".join(keywords)


def _first(values: list[str] | None) -> str:
    """Return the first non empty entry of *values*."""
    for value in values or []:
        text = str(value or "").strip()
        if text:
            return text
    return ""


register_adapter(EmailOutreachAdapter())
