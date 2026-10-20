"""Opportunity scoring.

The score explains *why* a candidate is worth working on. Every component
is computed from **observable** input only - the text that was really
fetched, the URL, the category and the declared submission method.

Metrics that would need a third party data set (domain authority, traffic
estimate, publication status, ...) are never guessed. They are reported in
``unavailable_metrics`` so the user can see that the score does not claim
to know them.

The structure of the result matches the ``ScoreBreakdown`` type of
``packages/shared-types``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from app.db.models import BusinessProfile

#: Metrics that are never available to the automation layer.
BASE_UNAVAILABLE_METRICS: tuple[str, ...] = (
    "domain_authority",
    "traffic_estimate",
    "publication_status",
)

#: Value of a category for the business value of an opportunity.
CATEGORY_VALUE: dict[str, int] = {
    "EDITORIAL": 8,
    "GUEST_POST": 7,
    "BUSINESS_DIRECTORY": 6,
    "INDUSTRY_DIRECTORY": 6,
    "LOCAL_CITATION": 6,
    "BUSINESS_PROFILE": 6,
    "RESOURCE_PAGE": 6,
    "SUPPLIER_PARTNER": 6,
    "DOCUMENT_SHARING": 5,
    "UNLINKED_MENTION": 5,
    "SOCIAL_PROFILE": 4,
    "PUBLIC_PROFILE": 4,
    "BROKEN_LINK": 4,
    "CUSTOM": 3,
    "FORUM_COMMUNITY": 3,
    "QA_CONTRIBUTION": 3,
    "IMAGE_ATTRIBUTION": 3,
    "BLOG_COMMENT": 2,
}

#: How much work a submission method costs (higher = cheaper).
METHOD_EFFORT: dict[str, int] = {
    "API": 10,
    "BROWSER_FORM": 8,
    "MANUAL": 6,
    "EMAIL_OUTREACH": 5,
    "UNKNOWN": 4,
}

#: Categories where a listing usually links back to the business website.
_LISTING_CATEGORIES = frozenset(
    {
        "BUSINESS_DIRECTORY",
        "INDUSTRY_DIRECTORY",
        "LOCAL_CITATION",
        "BUSINESS_PROFILE",
        "PUBLIC_PROFILE",
        "SOCIAL_PROFILE",
        "DOCUMENT_SHARING",
        "RESOURCE_PAGE",
    }
)

_EDITORIAL_CATEGORIES = frozenset(
    {"EDITORIAL", "GUEST_POST", "RESOURCE_PAGE", "BROKEN_LINK", "UNLINKED_MENTION"}
)

_EDITORIAL_MARKERS = (
    "guest post",
    "write for us",
    "write for our",
    "submit an article",
    "write an article",
    "become a contributor",
    "contributor",
    "editorial guidelines",
    "pitch",
)

_ALLOW_LINK_MARKERS = (
    "dofollow",
    "follow links",
    "links are allowed",
    "you may link",
    "you can link",
    "include a link",
    "link back",
    "backlink",
    "add a link",
)

_DENY_LINK_MARKERS = (
    "nofollow",
    "no follow",
    "we do not allow links",
    "we don't allow links",
    "no external links",
    "links are not allowed",
    "no linking",
)

_SUBMISSION_URL_MARKERS = (
    "/add-your-business",
    "/list-your-business",
    "/add-your-company",
    "/add-your-site",
    "/add-your-profile",
    "/submit-your-site",
    "/submit-your-listing",
    "/submit-website",
    "/create-listing",
    "/create-your-listing",
    "/get-listed",
    "/add-listing",
    "/business/add",
    "/write-for-us",
    "/contribute",
    "/submit",
    "/join",
)

_SUBMISSION_TEXT_MARKERS = (
    "add your business",
    "add your company",
    "add your website",
    "add your site",
    "add your profile",
    "submit your listing",
    "submit your site",
    "submit your profile",
    "submit your business",
    "create your listing",
    "get listed",
    "list your business",
    "claim your listing",
)

_SPAM_MARKERS = (
    "buy backlinks",
    "cheap backlinks",
    "backlinks for sale",
    "buy guest post",
    "guest post spam",
    "free backlinks",
    "backlink package",
    "seo backlinks",
)

_PAID_LINK_MARKERS = (
    "paid guest post",
    "paid link",
    "post your article for",
    "we pay for links",
)

_WORD = re.compile(r"[a-z0-9+#]+")


def score_opportunity(
    *,
    website_url: str,
    title: str = "",
    description: str = "",
    text: str = "",
    category: str = "",
    domain: str = "",
    profile: BusinessProfile | None = None,
    profile_keywords: Sequence[str] | None = None,
    submission_method: str = "UNKNOWN",
    registration_required: bool | None = None,
    requires_approval: bool | None = None,
    language: str | None = None,
    region: str | None = None,
    contact_email: str | None = None,
) -> dict[str, Any]:
    """Score a candidate opportunity and explain the result.

    The returned dictionary matches the ``ScoreBreakdown`` structure of the
    shared types: eight positive components, a spam penalty, the total and
    the explanation.
    """
    url = (website_url or "").strip()
    domain = (domain or _host_of(url)).strip().lower()
    title = (title or "").strip()
    description = (description or "").strip()
    body = (text or "").strip()
    haystack = " ".join([title, description, body, category, domain]).lower()

    keywords = _keywords(profile, profile_keywords)
    reasons: list[str] = []
    unavailable: list[str] = list(BASE_UNAVAILABLE_METRICS)

    topical, topical_reasons, topical_missing = _topical_relevance(
        haystack=haystack, keywords=keywords, domain=domain
    )
    reasons.extend(topical_reasons)
    unavailable.extend(topical_missing)

    quality, quality_reasons = _site_quality(url=url, domain=domain, body=body)
    reasons.extend(quality_reasons)

    editorial, editorial_reasons = _editorial_relevance(
        url=url, body=body, category=category
    )
    reasons.extend(editorial_reasons)

    links, link_reasons = _links_allowed(body=body, category=category)
    reasons.extend(link_reasons)

    documented, documented_reasons = _documented_submission(
        url=url, body=body, method=submission_method, contact_email=contact_email
    )
    reasons.extend(documented_reasons)

    effort, effort_reasons = _effort(
        method=submission_method,
        registration_required=registration_required,
        requires_approval=requires_approval,
    )
    reasons.extend(effort_reasons)

    business, business_reasons = _business_value(
        category=category, language=language, region=region, profile=profile
    )
    reasons.extend(business_reasons)

    relationship, relationship_reasons = _relationship(
        domain=domain, profile=profile, contact_email=contact_email
    )
    reasons.extend(relationship_reasons)

    penalty, penalty_reasons = _spam_penalty(body=body, domain=domain, profile=profile)
    reasons.extend(penalty_reasons)

    total = round(
        topical
        + quality
        + editorial
        + links
        + documented
        + effort
        + business
        + relationship
        - penalty
    )
    total = max(0, min(100, total))

    if not body:
        reasons.append(
            "The page text was not fetched, so the quality signals are based on the URL only."
        )
        unavailable.append("page_text")

    return {
        "topical_relevance": topical,
        "site_quality": quality,
        "editorial_relevance": editorial,
        "links_allowed": links,
        "documented_submission": documented,
        "effort": effort,
        "business_value": business,
        "relationship": relationship,
        "spam_penalty": penalty,
        "total": total,
        "reasons": reasons,
        "unavailable_metrics": sorted(set(unavailable)),
    }


# -- components -----------------------------------------------------------


def _topical_relevance(
    *, haystack: str, keywords: list[str], domain: str
) -> tuple[int, list[str], list[str]]:
    """How well the candidate matches the profile of the business."""
    if not keywords:
        return (
            0,
            ["No profile keywords were available, so the topical relevance stays neutral."],
            ["profile_keywords"],
        )
    matched = [keyword for keyword in keywords if keyword.lower() in haystack]
    score = round(20 * (len(matched) / len(keywords)))
    reasons = [
        f"{len(matched)} of {len(keywords)} profile keywords appear on the page"
        + (f": {', '.join(matched)}." if matched else ".")
    ]
    if domain and any(keyword.lower() in domain.lower() for keyword in keywords):
        score = min(20, score + 2)
        reasons.append("The domain itself contains one of the profile keywords.")
    return max(0, min(20, score)), reasons, []


def _site_quality(*, url: str, domain: str, body: str) -> tuple[int, list[str]]:
    """Observable quality signals of the opportunity page."""
    score = 0
    reasons: list[str] = []
    if url.lower().startswith("https://"):
        score += 2
        reasons.append("The opportunity page is served over HTTPS.")
    words = len(body.split())
    if words >= 400:
        score += 3
        reasons.append(f"The page contains {words} words of real content.")
    elif words >= 120:
        score += 1
        reasons.append(f"The page contains {words} words of content.")
    if re.search(r"about us|about the (company|business)|who we are", body, re.IGNORECASE):
        score += 3
        reasons.append("The page explains who operates the site.")
    if re.search(r"privacy policy|terms (of service|of use)", body, re.IGNORECASE):
        score += 2
        reasons.append("The site publishes legal information (privacy policy / terms).")
    if re.search(r"\b(inc|llc|ltd|gmbh|corp|corporation|company)\b", body, re.IGNORECASE):
        score += 1
        reasons.append("The page mentions a registered company.")
    if len(_tokens(body)) >= 150:
        score += 2
        reasons.append("The page has a broad vocabulary and is not a thin stub.")
    host = domain.split(".")[0] if domain else ""
    if host and re.fullmatch(r"[0-9]+", host):
        score -= 4
        reasons.append("The domain is an IP address, which is rarely a good target.")
    elif len(host) < 3:
        score -= 2
        reasons.append("The domain name is very short and therefore of low quality.")
    return max(0, min(15, score)), reasons


def _editorial_relevance(*, url: str, body: str, category: str) -> tuple[int, list[str]]:
    """How likely it is that the site accepts editorial content."""
    lowered = body.lower()
    markers = [marker for marker in _EDITORIAL_MARKERS if marker in lowered]
    path = url.lower().split("?", 1)[0]
    url_marker = any(marker in path for marker in ("/write-for-us", "/guest-post", "/contribute", "/authors"))

    if category in _EDITORIAL_CATEGORIES:
        score = 3
        reasons = [f"The category '{category}' describes a page that takes editorial submissions."]
        if markers:
            score += 4
            reasons.append(
                "The page explicitly invites contributions ("
                + ", ".join(sorted(set(markers))[:3])
                + ")."
            )
        if url_marker:
            score += 2
            reasons.append("The URL points at a dedicated contributor page.")
        if re.search(r"\b(article|blog post|post a)\b", lowered):
            score += 1
            reasons.append("The page talks about articles or posts.")
        return max(0, min(10, score)), reasons

    score = min(3, len(set(markers)))
    reasons: list[str] = []
    if score:
        reasons.append("The page mentions editorial contributions, although the category says otherwise.")
    return score, reasons


def _links_allowed(*, body: str, category: str) -> tuple[int, list[str]]:
    """Whether the page suggests that a link is allowed."""
    lowered = body.lower()
    allow = [marker for marker in _ALLOW_LINK_MARKERS if marker in lowered]
    deny = [marker for marker in _DENY_LINK_MARKERS if marker in lowered]

    score = 0
    reasons: list[str] = []
    if category in _LISTING_CATEGORIES:
        score += 6
        reasons.append(f"A listing of type '{category}' usually links back to the listed website.")
    elif category in _EDITORIAL_CATEGORIES:
        score += 5
        reasons.append("An editorial page usually links to the sources it mentions.")
    elif category in {"FORUM_COMMUNITY", "BLOG_COMMENT", "QA_CONTRIBUTION"}:
        score += 2
        reasons.append("Community platforms only accept links in rare cases.")
    if allow:
        score += 4
        reasons.append("The page states that links are allowed (" + ", ".join(allow[:2]) + ").")
    if deny:
        score -= 8
        reasons.append("The page states that links are not followed (" + ", ".join(deny[:2]) + ").")
    return max(0, min(15, score)), reasons


def _documented_submission(
    *, url: str, body: str, method: str, contact_email: str | None
) -> tuple[int, list[str]]:
    """How clearly the platform documents how to submit."""
    path = url.lower().split("?", 1)[0]
    lowered = body.lower()
    score = 0
    reasons: list[str] = []
    if any(marker in path for marker in _SUBMISSION_URL_MARKERS):
        score += 4
        reasons.append("The URL points at a dedicated submission page.")
    if any(marker in lowered for marker in _SUBMISSION_TEXT_MARKERS):
        score += 3
        reasons.append("The page explains how to add a business, listing or profile.")
    if contact_email:
        score += 1
        reasons.append("A contact address is known for this platform.")
    if method and method.upper() != "UNKNOWN":
        score += 2
        reasons.append(f"The submission method '{method}' is known.")
    return max(0, min(10, score)), reasons


def _effort(
    *,
    method: str,
    registration_required: bool | None,
    requires_approval: bool | None,
) -> tuple[int, list[str]]:
    """How much work the submission is (higher score = less work)."""
    key = (method or "UNKNOWN").upper()
    score = METHOD_EFFORT.get(key, 4)
    reasons = [f"The submission method '{key}' was taken into account."]
    if registration_required is True:
        score -= 3
        reasons.append("An account is required before the submission can be made.")
    elif registration_required is False:
        score += 1
        reasons.append("No account is required for the submission.")
    if requires_approval:
        score -= 1
        reasons.append("The listing has to be approved by the platform before it is published.")
    return max(0, min(10, score)), reasons


def _business_value(
    *,
    category: str,
    language: str | None,
    region: str | None,
    profile: BusinessProfile | None,
) -> tuple[int, list[str]]:
    """How valuable the opportunity is for the business."""
    key = (category or "").upper()
    score = CATEGORY_VALUE.get(key, 3)
    reasons = [f"The category '{category or 'unknown'}' has a business value of {score} of 10."]
    if profile is not None and region:
        targets = {str(item).upper() for item in (profile.target_countries or [])}
        targets.update(str(item).upper() for item in (profile.target_regions or []))
        if region.upper() in targets:
            score += 3
            reasons.append(f"The region '{region}' is one of the target regions of the profile.")
        else:
            reasons.append(f"The region '{region}' is not a target region of the profile.")
    if profile is not None and language:
        preferred = (profile.preferred_language or "").lower()
        if preferred and language.lower() == preferred:
            score += 1
            reasons.append(f"The language '{language}' matches the preferred language of the profile.")
    return max(0, min(10, score)), reasons


def _relationship(
    *, domain: str, profile: BusinessProfile | None, contact_email: str | None
) -> tuple[int, list[str]]:
    """Existing relationship with the platform."""
    score = 0
    reasons: list[str] = []
    if profile is not None:
        targets = {str(item).lower().removeprefix("www.") for item in (profile.target_domains or [])}
        if domain and domain.removeprefix("www.") in targets:
            score += 5
            reasons.append("The domain is already a target domain of the profile.")
        social = {
            str(value).lower().removeprefix("www.")
            for value in (profile.social_profiles or {}).values()
            if value
        }
        if domain and domain.removeprefix("www.") in social:
            score += 3
            reasons.append("The business already has a profile on this platform.")
    if contact_email:
        score += 2
        reasons.append("A direct contact address is known, which makes the outreach easier.")
    return max(0, min(5, score)), reasons


def _spam_penalty(
    *, body: str, domain: str, profile: BusinessProfile | None
) -> tuple[int, list[str]]:
    """Penalty for candidates that look like spam networks."""
    lowered = body.lower()
    score = 0
    reasons: list[str] = []
    if profile is not None:
        excluded = {
            str(item).lower().removeprefix("www.") for item in (profile.excluded_domains or [])
        }
        if domain and domain.removeprefix("www.") in excluded:
            score += 20
            reasons.append("The domain is on the exclusion list of the profile.")
    spam = [marker for marker in _SPAM_MARKERS if marker in lowered]
    if spam:
        score += 10
        reasons.append("The page advertises paid or cheap backlinks (" + ", ".join(spam[:2]) + ").")
    paid = [marker for marker in _PAID_LINK_MARKERS if marker in lowered]
    if paid:
        score += 5
        reasons.append("The page sells links instead of accepting editorial submissions.")
    return max(0, min(20, score)), reasons


# -- helpers --------------------------------------------------------------


def _tokens(value: str) -> set[str]:
    """The distinct words of *value*."""
    return {token for token in _WORD.findall((value or "").lower()) if len(token) > 2}


def _host_of(url: str) -> str:
    """The host of *url* without the ``www.`` prefix."""
    text = (url or "").strip().lower()
    for scheme in ("https://", "http://"):
        if text.startswith(scheme):
            text = text[len(scheme) :]
            break
    return text.split("/")[0].split(":")[0].removeprefix("www.")


def _keywords(
    profile: BusinessProfile | None, profile_keywords: Sequence[str] | None
) -> list[str]:
    """The keywords the topical relevance is measured against."""
    raw: list[str] = [str(item) for item in (profile_keywords or []) if str(item).strip()]
    if not raw and profile is not None:
        raw = [str(item) for item in (profile.keywords or []) if str(item).strip()]
    if not raw and profile is not None:
        for value in (profile.niche, profile.industry):
            if value and str(value).strip():
                raw.append(str(value).strip())
    return raw
