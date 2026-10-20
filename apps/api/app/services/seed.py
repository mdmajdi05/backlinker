"""Registry seeding: categories, adapters and discovery sources.

Seeding is idempotent - it inserts missing registry rows and updates the
metadata of existing ones, so upgrading the application keeps user data.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import AutomationAdapter, DiscoverySource, OpportunityCategory

log = get_logger(__name__)

CATEGORIES: list[dict] = [
    {
        "key": "BUSINESS_DIRECTORY",
        "name": "Business directories",
        "description": "General purpose business listing directories.",
        "submission_methods": ["BROWSER_FORM", "MANUAL", "EMAIL_OUTREACH"],
        "required_fields": ["name", "website", "description"],
        "verification_rules": {"expect_link": True, "follow_redirect": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "INDUSTRY_DIRECTORY",
        "name": "Industry directories",
        "description": "Vertical directories for a specific industry or niche.",
        "submission_methods": ["BROWSER_FORM", "MANUAL", "API"],
        "required_fields": ["name", "website", "description"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "LOCAL_CITATION",
        "name": "Local citations",
        "description": "Local business listings and citation sources.",
        "submission_methods": ["BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "address_region"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "BUSINESS_PROFILE",
        "name": "Business profiles",
        "description": "Company profile pages (company about pages, marketplaces).",
        "submission_methods": ["BROWSER_FORM", "MANUAL", "API"],
        "required_fields": ["name", "website", "description"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "SOCIAL_PROFILE",
        "name": "Social profiles",
        "description": "Social networks where a profile link can be added.",
        "submission_methods": ["BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "PUBLIC_PROFILE",
        "name": "Public profile pages",
        "description": "Creator, expert and portfolio profiles.",
        "submission_methods": ["BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "description"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "EDITORIAL",
        "name": "Editorial backlinks",
        "description": "Editorial mentions and articles that may link to the site.",
        "submission_methods": ["EMAIL_OUTREACH", "MANUAL"],
        "required_fields": ["name", "website", "pitch"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "GUEST_POST",
        "name": "Guest posting",
        "description": "Write an article for a publisher that links back.",
        "submission_methods": ["EMAIL_OUTREACH", "BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "pitch", "author_bio"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "RESOURCE_PAGE",
        "name": "Resource pages",
        "description": "Curated resource lists that accept new entries.",
        "submission_methods": ["EMAIL_OUTREACH", "BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "pitch"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "SUPPLIER_PARTNER",
        "name": "Supplier and partner pages",
        "description": "Partner, supplier and integration directories.",
        "submission_methods": ["EMAIL_OUTREACH", "BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "pitch"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "FORUM_COMMUNITY",
        "name": "Forums and communities",
        "description": "Community platforms where relevant participation is allowed.",
        "submission_methods": ["BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "topic"],
        "verification_rules": {"expect_link": False},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "BLOG_COMMENT",
        "name": "Blog comments",
        "description": "Comment sections that permit relevant links.",
        "submission_methods": ["BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "comment"],
        "verification_rules": {"expect_link": False},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "QA_CONTRIBUTION",
        "name": "Q&A contributions",
        "description": "Question and answer platforms accepting authoritative answers.",
        "submission_methods": ["BROWSER_FORM", "MANUAL"],
        "required_fields": ["name", "website", "answer"],
        "verification_rules": {"expect_link": False},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "IMAGE_ATTRIBUTION",
        "name": "Image attribution",
        "description": "Stock and media libraries allowing attribution links.",
        "submission_methods": ["BROWSER_FORM", "MANUAL", "API"],
        "required_fields": ["name", "website", "image_url"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "DOCUMENT_SHARING",
        "name": "Document and resource sharing",
        "description": "Document, slide and resource sharing platforms.",
        "submission_methods": ["BROWSER_FORM", "MANUAL", "API"],
        "required_fields": ["name", "website", "document_url"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "BROKEN_LINK",
        "name": "Broken link outreach",
        "description": "Outreach to pages linking to a broken resource.",
        "submission_methods": ["EMAIL_OUTREACH", "MANUAL"],
        "required_fields": ["name", "website", "broken_url"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "UNLINKED_MENTION",
        "name": "Unlinked brand mentions",
        "description": "Mentions of the brand that are not yet linked.",
        "submission_methods": ["EMAIL_OUTREACH", "MANUAL"],
        "required_fields": ["name", "website", "mention_url"],
        "verification_rules": {"expect_link": True},
        "automatable": False,
        "requires_approval": True,
    },
    {
        "key": "CUSTOM",
        "name": "Custom category",
        "description": "User defined opportunity category.",
        "submission_methods": ["MANUAL"],
        "required_fields": ["name", "website"],
        "verification_rules": {},
        "automatable": False,
        "requires_approval": True,
    },
]

ADAPTERS: list[dict] = [
    {
        "key": "generic_manual",
        "name": "Manual assisted submission",
        "kind": "MANUAL_ASSISTED",
        "description": "Prepares the submission pack (URLs, anchor text, description) and hands the task to the operator.",
        "supported_categories": [],
        "supported_methods": ["MANUAL"],
        "supported_environments": ["CLOUD", "LOCAL"],
        "required_config": {},
        "required_user_fields": ["name", "website", "description"],
        "registration_required": False,
        "manual_approval_required": True,
        "automatable": False,
        "verification_method": "manual",
        "retryable_errors": [],
        "restrictions": "Requires a human to complete the submission on the target website.",
        "success_signals": ["Operator confirms the listing was created"],
        "domains": [],
        "implementation": "app.services.adapters.impl.manual:ManualAdapter",
    },
    {
        "key": "http_form",
        "name": "Configurable HTTP form adapter",
        "kind": "BROWSER_AUTOMATION",
        "description": "Submits a plain HTML form using configured selectors. No JavaScript execution.",
        "supported_categories": [],
        "supported_methods": ["BROWSER_FORM"],
        "supported_environments": ["CLOUD", "LOCAL"],
        "required_config": {
            "form_url": "string - URL of the submission form",
            "fields": "object - CSS selector to value mapping",
            "success_selector": "string - CSS selector proving success",
            "submit_selector": "string - CSS selector of the submit button",
        },
        "required_user_fields": ["name", "website", "description"],
        "registration_required": False,
        "manual_approval_required": False,
        "automatable": True,
        "verification_method": "http_link_check",
        "retryable_errors": ["timeout", "connection_reset", "http_5xx"],
        "restrictions": "Only works on sites that accept standard form posts without JavaScript challenges.",
        "success_signals": ["Success selector present in the response"],
        "domains": [],
        "implementation": "app.services.adapters.impl.http_form:HttpFormAdapter",
    },
    {
        "key": "playwright_form",
        "name": "Playwright browser adapter",
        "kind": "BROWSER_AUTOMATION",
        "description": "Permitted browser automation driven by configured selectors.",
        "supported_categories": [],
        "supported_methods": ["BROWSER_FORM"],
        "supported_environments": ["CLOUD", "LOCAL"],
        "required_config": {
            "form_url": "string - URL of the submission form",
            "fields": "object - CSS selector to value mapping",
            "success_selector": "string - CSS selector proving success",
        },
        "required_user_fields": ["name", "website", "description"],
        "registration_required": False,
        "manual_approval_required": False,
        "automatable": True,
        "verification_method": "http_link_check",
        "retryable_errors": ["timeout", "connection_reset", "http_5xx"],
        "restrictions": "Pauses for manual intervention when a CAPTCHA or login challenge is detected.",
        "success_signals": ["Success selector present after submission"],
        "domains": [],
        "implementation": "app.services.adapters.impl.playwright_form:PlaywrightFormAdapter",
    },
    {
        "key": "email_outreach",
        "name": "Email outreach adapter",
        "kind": "EMAIL_OUTREACH",
        "description": "Drafts a personalised outreach email. Sending requires explicit operator confirmation.",
        "supported_categories": [],
        "supported_methods": ["EMAIL_OUTREACH"],
        "supported_environments": ["CLOUD", "LOCAL"],
        "required_config": {
            "contact_email": "string - recipient address",
            "tone": "string - optional tone instruction for the draft",
        },
        "required_user_fields": ["name", "website", "description", "author_bio"],
        "registration_required": False,
        "manual_approval_required": True,
        "automatable": True,
        "verification_method": "manual",
        "retryable_errors": [],
        "restrictions": "Drafts are never sent automatically without operator approval.",
        "success_signals": ["Draft created and stored on the task"],
        "domains": [],
        "implementation": "app.services.adapters.impl.email_outreach:EmailOutreachAdapter",
    },
    {
        "key": "json_api",
        "name": "Documented JSON API adapter",
        "kind": "OFFICIAL_API",
        "description": "Submits to a documented JSON endpoint using configured headers and payload template.",
        "supported_categories": [],
        "supported_methods": ["API"],
        "supported_environments": ["CLOUD", "LOCAL"],
        "required_config": {
            "endpoint": "string - fully qualified API endpoint",
            "method": "string - HTTP method (default POST)",
            "headers": "object - static headers (secrets belong in integration credentials)",
            "payload_template": "object - JSON body template with {{placeholders}}",
            "success_field": "string - JSON field proving success",
        },
        "required_user_fields": ["name", "website", "description"],
        "registration_required": False,
        "manual_approval_required": False,
        "automatable": True,
        "verification_method": "http_link_check",
        "retryable_errors": ["timeout", "connection_reset", "http_5xx", "http_429"],
        "restrictions": "Only use endpoints the site documents for public submissions.",
        "success_signals": ["Response contains the configured success field"],
        "domains": [],
        "implementation": "app.services.adapters.impl.json_api:JsonApiAdapter",
    },
]

DISCOVERY_SOURCES: list[dict] = [
    {
        "key": "manual_seed",
        "name": "User supplied seeds",
        "description": "Uses the URLs and domains the operator provides.",
        "kind": "seed",
        "requires_credentials": False,
        "config_schema": {"seeds": "array of URLs"},
        "categories": [],
    },
    {
        "key": "brave_search",
        "name": "Brave Search API",
        "description": "Web search results from the official Brave Search API.",
        "kind": "search_api",
        "requires_credentials": True,
        "config_schema": {"api_key": "Brave Search API subscription key"},
        "categories": [],
    },
    {
        "key": "serpapi",
        "name": "SerpAPI",
        "description": "Search results through SerpAPI (Google, Bing, ...).",
        "kind": "search_api",
        "requires_credentials": True,
        "config_schema": {"api_key": "SerpAPI key"},
        "categories": [],
    },
    {
        "key": "directory_index",
        "name": "Public directory index",
        "description": "Built-in catalogue of publicly documented submission pages. Reachability is verified live.",
        "kind": "directory",
        "requires_credentials": False,
        "config_schema": {"countries": "optional ISO country codes"},
        "categories": [
            "BUSINESS_DIRECTORY",
            "INDUSTRY_DIRECTORY",
            "BUSINESS_PROFILE",
            "LOCAL_CITATION",
            "SOCIAL_PROFILE",
            "PUBLIC_PROFILE",
        ],
    },
    {
        "key": "imported_dataset",
        "name": "Imported dataset",
        "description": "Opportunities imported from Excel or CSV files.",
        "kind": "import",
        "requires_credentials": False,
        "config_schema": {},
        "categories": [],
    },
]


def seed_registry(db: Session) -> None:
    """Insert / refresh the category, adapter and discovery registries."""
    changed = False

    for spec in CATEGORIES:
        existing = db.execute(
            select(OpportunityCategory).where(OpportunityCategory.key == spec["key"])
        ).scalar_one_or_none()
        if existing is None:
            db.add(OpportunityCategory(**spec))
            changed = True
        else:
            for field, value in spec.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True

    for spec in ADAPTERS:
        existing = db.execute(
            select(AutomationAdapter).where(AutomationAdapter.key == spec["key"])
        ).scalar_one_or_none()
        if existing is None:
            db.add(AutomationAdapter(**spec))
            changed = True
        else:
            for field, value in spec.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True

    for spec in DISCOVERY_SOURCES:
        existing = db.execute(
            select(DiscoverySource).where(DiscoverySource.key == spec["key"])
        ).scalar_one_or_none()
        if existing is None:
            db.add(DiscoverySource(**spec))
            changed = True

    if changed:
        db.commit()
        log.info("registry seeded")
