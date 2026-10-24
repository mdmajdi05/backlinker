"""Guided per website setup of automatic form submission.

The automatic adapters need three facts that only the target page knows:

* the URL of the form,
* which HTML control receives which business value,
* the signal that proves the submission succeeded.

This module turns those facts into the configuration the adapters already
understand.  It also offers a best effort detector that reads the static HTML
of a form and proposes selectors.  Detection never submits anything and never
marks a website as automated on its own - the operator reviews the result.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.net import safe_get, validate_http_url
from app.db.base import utcnow
from app.db.models import AutomationAdapter, Website

#: The values an operator can place into a form control.
PLACEHOLDERS: tuple[tuple[str, str], ...] = (
    ("name", "Company name"),
    ("website", "Website"),
    ("landing_page", "Landing page"),
    ("description", "Description"),
    ("anchor", "Anchor text"),
    ("email", "E-mail"),
    ("phone", "Phone"),
    ("address", "Address"),
    ("city", "City"),
    ("state", "State / region"),
    ("country", "Country"),
    ("postal_code", "Postal code"),
    ("industry", "Industry"),
    ("niche", "Niche"),
    ("category", "Category"),
    ("region", "Region"),
    ("language", "Language"),
)

PLACEHOLDER_TOKENS = {key for key, _label in PLACEHOLDERS}
AUTOMATIC_ADAPTERS = {"playwright_form", "http_form"}
MAX_FIELDS = 40
MAX_SELECTOR = 300
MAX_TEMPLATE = 1000

#: Words that identify a form control, longest/most specific first.
_TOKEN_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("e-mail", "e mail", "email"), "email"),
    (("phone", "telephone", "tel", "mobile"), "phone"),
    (("postal", "postcode", "zip"), "postal_code"),
    (("state", "region", "province"), "state"),
    (("country",), "country"),
    (("city", "town", "locality"), "city"),
    (("street", "address"), "address"),
    (("website", "web site", "homepage", "home page"), "website"),
    (("landing", "target url", "destination"), "landing_page"),
    (("anchor",), "anchor"),
    (("description", "about", "bio", "summary", "message", "comment", "details"), "description"),
    (("category", "categories"), "category"),
    (("industry", "sector"), "industry"),
    (("niche",), "niche"),
    (("language", "locale"), "language"),
    (("company", "business", "organisation", "organization", "brand"), "name"),
)

_CAPTCHA_MARKERS = ("recaptcha", "hcaptcha", "captcha", "cf-turnstile", "turnstile")
_SKIP_INPUT_TYPES = {
    "hidden",
    "submit",
    "button",
    "reset",
    "image",
    "file",
    "password",
    "search",
}


class AutomationSetupError(Exception):
    """A configuration that cannot be saved."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def placeholder_label(token: str) -> str:
    for key, label in PLACEHOLDERS:
        if key == token:
            return label
    return token


def detect_fields(db: Session, website: Website, form_url: str = "") -> dict[str, Any]:
    """Read the form page and propose selectors for the known values.

    Only static HTML is inspected.  A JavaScript rendered form returns an empty
    list; the operator can then add the selectors by hand or keep the website
    on the manual path.
    """
    del db  # the detector is intentionally independent of the database
    config = website.adapter_config if isinstance(website.adapter_config, dict) else {}
    url = (form_url or str(config.get("form_url") or "") or website.opportunity_url or "").strip()
    if not url:
        raise AutomationSetupError("A form URL is required")
    try:
        url = validate_http_url(url)
    except ValueError as exc:
        raise AutomationSetupError(str(exc)) from exc

    response = safe_get(url, allow_robots=settings.respect_robots)
    result: dict[str, Any] = {
        "form_url": url,
        "final_url": response.final_url,
        "reachable": False,
        "http_status": response.status_code,
        "form_found": False,
        "fields": [],
        "has_captcha": False,
        "has_password": False,
        "message": "",
    }
    if response.error:
        result["message"] = response.error
        return result
    if response.status_code >= 400:
        result["message"] = f"The form page answered with HTTP {response.status_code}."
        return result

    result["reachable"] = True
    soup = BeautifulSoup(response.content, "lxml")
    lowered = response.content.lower()
    result["has_captcha"] = any(marker in lowered for marker in _CAPTCHA_MARKERS)
    result["has_password"] = bool(soup.find("input", {"type": "password"}))

    forms = soup.find_all("form")
    result["form_found"] = bool(forms)
    fields = _best_form_fields(forms, soup)
    result["fields"] = fields
    if fields:
        result["message"] = (
            f"{len(fields)} field(s) were found. Review the mapping before saving."
            + (
                " A CAPTCHA was detected: the automation will pause for a human."
                if result["has_captcha"]
                else ""
            )
        )
    else:
        result["message"] = (
            "No named form controls were found. The form may be rendered by "
            "JavaScript, or it may not be a public submission form. Use the "
            "manual path or add the selectors by hand."
        )
    return result


def save_automation(
    db: Session,
    website: Website,
    payload: dict[str, Any],
) -> Website:
    """Validate and store the per website automatic form configuration."""
    adapter_key = str(payload.get("adapter") or "").strip()
    if not adapter_key:
        return clear_automation(db, website)
    if adapter_key not in AUTOMATIC_ADAPTERS:
        raise AutomationSetupError(
            f"'{adapter_key}' is not an automatic form adapter "
            f"({', '.join(sorted(AUTOMATIC_ADAPTERS))})"
        )
    adapter = db.execute(
        select(AutomationAdapter).where(AutomationAdapter.key == adapter_key)
    ).scalar_one_or_none()
    if adapter is None:
        raise AutomationSetupError(f"The adapter '{adapter_key}' is not registered", 404)

    form_url = str(payload.get("form_url") or "").strip()
    if not form_url:
        raise AutomationSetupError("A form URL is required")
    try:
        form_url = validate_http_url(form_url)
    except ValueError as exc:
        raise AutomationSetupError(str(exc)) from exc

    raw_fields = payload.get("fields") or {}
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise AutomationSetupError("Add at least one form field with a CSS selector")
    if len(raw_fields) > MAX_FIELDS:
        raise AutomationSetupError(f"At most {MAX_FIELDS} fields are supported")
    fields: dict[str, str] = {}
    for selector, template in raw_fields.items():
        selector_text = str(selector or "").strip()
        template_text = str(template or "").strip()
        if not selector_text or not template_text:
            raise AutomationSetupError("Every field needs a selector and a value")
        if len(selector_text) > MAX_SELECTOR:
            raise AutomationSetupError("A CSS selector is too long")
        if len(template_text) > MAX_TEMPLATE:
            raise AutomationSetupError("A field value is too long")
        fields[selector_text] = template_text

    success_kind = str(payload.get("success_kind") or "text").strip().lower()
    success_value = str(payload.get("success_value") or "").strip()
    if success_kind not in {"text", "selector", "url"}:
        raise AutomationSetupError("Choose a valid success signal")
    if not success_value:
        raise AutomationSetupError(
            "Enter the success signal that appears after a successful submission"
        )
    if adapter_key == "http_form" and success_kind == "url":
        raise AutomationSetupError(
            "The HTTP form adapter cannot check the URL; use a success text or selector"
        )

    config: dict[str, Any] = {
        "adapter": adapter_key,
        "form_url": form_url,
        "fields": fields,
        "success_kind": success_kind,
        "success_value": success_value,
    }
    if success_kind == "text":
        config["success_text"] = success_value
    elif success_kind == "selector":
        config["success_selector"] = success_value
    else:
        config["success_url_contains"] = success_value
    submit_selector = str(payload.get("submit_selector") or "").strip()
    if submit_selector:
        config["submit_selector"] = submit_selector
    timeout_ms = payload.get("timeout_ms")
    if timeout_ms:
        try:
            config["timeout_ms"] = max(5000, min(int(timeout_ms), 120_000))
        except (TypeError, ValueError) as exc:
            raise AutomationSetupError("The timeout must be a number of milliseconds") from exc

    # Remember how the website was handled before the automatic setup so
    # clearing the setup does not silently change its nature.
    previous = website.adapter_config if isinstance(website.adapter_config, dict) else {}
    config["original_submission_method"] = str(
        previous.get("original_submission_method")
        or website.submission_method
        or "MANUAL"
    )
    website.adapter_id = adapter.id
    website.adapter_config = config
    # Both adapters use the BROWSER_FORM method in the registry.
    website.submission_method = "BROWSER_FORM"
    website.version += 1
    website.updated_at = utcnow()
    db.commit()
    db.refresh(website)
    return website


def clear_automation(db: Session, website: Website) -> Website:
    """Remove the explicit adapter and return the website to the manual path."""
    previous = website.adapter_config if isinstance(website.adapter_config, dict) else {}
    website.submission_method = str(
        previous.get("original_submission_method") or "MANUAL"
    )
    website.adapter_id = None
    website.adapter_config = None
    website.version += 1
    website.updated_at = utcnow()
    db.commit()
    db.refresh(website)
    return website


def automation_payload(website: Website) -> dict[str, Any] | None:
    """The normalized configuration shown by the clients (or ``None``)."""
    config = website.adapter_config
    if not isinstance(config, dict) or not config:
        return None
    raw_fields = config.get("fields")
    fields = raw_fields if isinstance(raw_fields, dict) else {}
    return {
        "adapter": str(config.get("adapter") or (website.adapter.key if website.adapter else "")),
        "form_url": str(config.get("form_url") or ""),
        "fields": {
            str(selector): str(template)
            for selector, template in fields.items()
            if str(selector).strip()
        },
        "success_kind": str(config.get("success_kind") or "text"),
        "success_value": str(
            config.get("success_value")
            or config.get("success_text")
            or config.get("success_selector")
            or config.get("success_url_contains")
            or ""
        ),
        "submit_selector": str(config.get("submit_selector") or ""),
        "timeout_ms": config.get("timeout_ms"),
    }


# --------------------------------------------------------------------------
# Field detection helpers
# --------------------------------------------------------------------------
def _best_form_fields(forms: list[Any], soup: BeautifulSoup) -> list[dict[str, str]]:
    """Pick the form that looks like a submission form and describe it.

    A page often contains a search form before the real submission form.  The
    first ``<form>`` is therefore not automatically the right one: the form
    with the most usable controls (and without a password field) wins.
    """
    candidates = forms or [soup]
    best: list[dict[str, str]] = []
    best_score = -1
    for form in candidates:
        fields: list[dict[str, str]] = []
        seen: set[str] = set()
        for control in form.find_all(["input", "textarea", "select"]):
            field = _field_payload(control, soup)
            if field is None or field["selector"] in seen:
                continue
            seen.add(field["selector"])
            fields.append(field)
            if len(fields) >= MAX_FIELDS:
                break
        token_names = {field["token"] for field in fields if field["token"]}
        score = len(fields) + len(token_names) * 2
        if {"name", "email", "website", "description"} & token_names:
            score += 10
        if any(field["kind"] == "textarea" for field in fields):
            score += 2
        if form.find("input", {"type": "password"}) is not None:
            score -= 20
        if score > best_score:
            best_score = score
            best = fields
    return best


def _field_payload(control: Any, soup: BeautifulSoup) -> dict[str, str] | None:
    """Describe one form control - or return ``None`` when it is not usable."""
    tag = (control.name or "").lower()
    input_type = str(control.get("type") or ("textarea" if tag == "textarea" else "text")).lower()
    if tag == "input" and input_type in _SKIP_INPUT_TYPES:
        return None
    if input_type == "password":
        return None

    selector = _selector(control, tag, input_type)
    if not selector:
        return None
    label = _label(control, soup)
    token = _token_for(label)
    return {
        "selector": selector,
        "label": label or selector,
        "token": token,
        "kind": "textarea" if tag == "textarea" else "select" if tag == "select" else "input",
        "input_type": input_type,
    }


def _selector(control: Any, tag: str, input_type: str) -> str:
    element_id = str(control.get("id") or "").strip()
    if element_id:
        return f'[id="{_escape_attr(element_id)}"]'
    name = str(control.get("name") or "").strip()
    if name:
        return f'[name="{_escape_attr(name)}"]'
    if input_type not in ("text", "textarea") and input_type:
        return f'{tag}[type="{_escape_attr(input_type)}"]'
    return ""


def _label(control: Any, soup: BeautifulSoup) -> str:
    element_id = str(control.get("id") or "").strip()
    if element_id:
        label = soup.find("label", attrs={"for": element_id})
        if label is not None and label.get_text(" ", strip=True):
            return label.get_text(" ", strip=True)
    parent = control.find_parent("label")
    if parent is not None and parent.get_text(" ", strip=True):
        return parent.get_text(" ", strip=True)
    for attr in ("aria-label", "placeholder", "title"):
        value = str(control.get(attr) or "").strip()
        if value:
            return value
    return str(control.get("name") or control.get("id") or "").strip()


def _token_for(label: str) -> str:
    text = re.sub(r"[_\-\[\]]+", " ", (label or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if "first name" in text or "last name" in text:
        return ""
    for hints, token in _TOKEN_HINTS:
        if any(hint in text for hint in hints):
            return token
    if text in ("name", "full name", "your name"):
        return "name"
    return ""


def _escape_attr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
