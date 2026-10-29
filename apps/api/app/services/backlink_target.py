"""Find the exact page of a website where a backlink can be placed.

After the account of a row is active the system has a real, logged-in browser.
This module walks that session (never an anonymous fetch) and scores every
plausible target:

* submission pages (``/add-listing``, ``/submit``, ``/post`` ...),
* profile / account editors (a bio or website field is a real backlink place),
* forum / community "new thread" pages,
* comment forms.

A target is only reported when the **live page** really carries an input for a
URL / content field and a way to submit it.  The result stores the URL, the
field mapping and a confidence, so the submitter can fill it later and the
report shows exactly where the link will go.
"""

from __future__ import annotations

import re
import urllib.parse
from contextlib import suppress
from typing import Any

#: Links and paths that usually lead to a place where a link can be placed.
_TARGET_WORDS = (
    "submit",
    "add listing",
    "add your",
    "add business",
    "add website",
    "add site",
    "add url",
    "get listed",
    "list your",
    "new listing",
    "place ad",
    "post ad",
    "classified",
    "submit your",
    "post",
    "new thread",
    "new topic",
    "create thread",
    "write",
    "blog",
    "publish",
    "profile",
    "my account",
    "account settings",
    "edit profile",
    "dashboard",
    "community",
    "forum",
    "directory",
)

#: Path fragments that make a URL a likely target.
_TARGET_PATHS = (
    "/submit",
    "/submit-listing",
    "/add",
    "/add-listing",
    "/add-business",
    "/add-website",
    "/get-listed",
    "/list-your",
    "/new-listing",
    "/listing/new",
    "/place/new",
    "/classifieds/new",
    "/create",
    "/post",
    "/new-post",
    "/new-thread",
    "/new-topic",
    "/publish",
    "/write",
    "/profile",
    "/profile/edit",
    "/user/profile",
    "/my-account",
    "/account/profile",
    "/settings/profile",
    "/account",
    "/settings",
    "/dashboard",
    "/directory",
)

#: Values that are never a backlink target.
_SKIP_PATHS = (
    "/login",
    "/signin",
    "/sign-in",
    "/register",
    "/signup",
    "/sign-up",
    "/logout",
    "/privacy",
    "/terms",
    "/cookie",
    "/cart",
    "/checkout",
    "/search",
)

#: Field names / labels that carry a link or a description.
_URL_TOKENS = ("url", "website", "web site", "homepage", "home page", "domain", "link")
_ANCHOR_TOKENS = ("anchor", "link text", "title")
_CONTENT_TOKENS = ("description", "content", "bio", "about", "message", "comment", "body", "post")
_TOKEN_WORDS = (
    "url",
    "website",
    "homepage",
    "domain",
    "link",
    "anchor",
    "description",
    "content",
    "bio",
    "message",
    "comment",
    "body",
    "post",
    "title",
)

_LOGIN_MARKERS = (
    "sign in to continue",
    "log in to continue",
    "please sign in",
    "please log in",
    "login required",
    "you must be logged in",
    "create a free account to continue",
)

#: Confidence at which a target is considered found.
FOUND_AT = 45

MAX_CANDIDATES = 12
MAX_INSPECT = 8


def _field_token(field: dict[str, Any]) -> str:
    """A semantic token for a form field (url / anchor / content / ...)."""
    raw = " ".join(
        str(field.get(key) or "")
        for key in ("name", "id", "placeholder", "label", "autocomplete")
    ).lower()
    text = re.sub(r"[_\-\[\]]+", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if any(hint in text for hint in ("e-mail", "e mail", "email")):
        return "email"
    if any(hint in text for hint in ("anchor", "link text")):
        return "anchor"
    if any(
        hint in text
        for hint in ("url", "website", "web site", "homepage", "home page", "domain", "web address")
    ):
        return "url"
    if any(
        hint in text
        for hint in ("description", "content", "bio", "about", "message", "comment", "body", "post")
    ):
        return "content"
    if "title" in text:
        return "title"
    return ""


def score_page(
    *,
    url: str,
    title: str,
    link_text: str,
    fields: list[dict[str, Any]],
    has_submit: bool,
    body_text: str = "",
) -> tuple[int, list[str]]:
    """Score one candidate page (0-100) and explain the score.

    Pure function so the ranking is testable without a browser.
    """
    lowered_url = urllib.parse.urlparse(url).path.lower()
    lowered_text = f"{title} {link_text} {body_text}".lower()
    score = 0
    reasons: list[str] = []

    tokens = {_field_token(field) for field in fields}
    if tokens & set(_URL_TOKENS):
        score += 38
        reasons.append("has a URL / website field")
    if tokens & set(_ANCHOR_TOKENS):
        score += 8
        reasons.append("has an anchor / title field")
    if tokens & set(_CONTENT_TOKENS):
        score += 20
        reasons.append("has a text / description field")
    if has_submit:
        score += 15
        reasons.append("has a submit button")

    if any(word in lowered_text for word in _TARGET_WORDS):
        score += 14
        reasons.append("page or link says submit / add / post")
    if any(part in lowered_url for part in _TARGET_PATHS):
        score += 10
        reasons.append("URL looks like a submission or profile page")
    if any(part in lowered_url for part in _SKIP_PATHS):
        score -= 60
        reasons.append("login / legal / search page")
    if any(marker in lowered_text for marker in _LOGIN_MARKERS):
        score -= 50
        reasons.append("login wall")
    if not fields:
        score -= 40
        reasons.append("no form fields")

    return max(0, min(100, score)), reasons


#: Collect the forms of the current page, including labels and selectors.
_COLLECT_JS = r"""
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden"
      && box.width > 1 && box.height > 1;
  };
  const labelFor = (el) => {
    const parts = [];
    if (el.labels) for (const label of el.labels) parts.push(label.innerText || "");
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      for (const id of labelledBy.split(/\s+/)) {
        const node = document.getElementById(id);
        if (node) parts.push(node.innerText || "");
      }
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const selectorFor = (el) => {
    if (el.id) return "#" + CSS.escape(el.id);
    const name = el.getAttribute("name");
    if (name) return el.tagName.toLowerCase() + "[name=\"" + CSS.escape(name) + "\"]";
    return null;
  };
  const fields = [];
  const seen = new Set();
  for (const el of document.querySelectorAll("input, textarea, select, [contenteditable='true']")) {
    if (!visible(el)) continue;
    const type = (el.getAttribute("type") || el.tagName).toLowerCase();
    if (["hidden", "submit", "button", "reset", "file", "image"].includes(type)) continue;
    const selector = selectorFor(el);
    if (!selector || seen.has(selector)) continue;
    seen.add(selector);
    fields.push({
      selector,
      name: el.getAttribute("name") || "",
      id: el.id || "",
      type,
      placeholder: el.getAttribute("placeholder") || "",
      autocomplete: el.getAttribute("autocomplete") || "",
      label: labelFor(el),
    });
  }
  const buttons = Array.from(document.querySelectorAll(
    "button, input[type='submit'], [role='button']"
  )).filter(visible).map((el) => (el.innerText || el.value || "").trim()).filter(Boolean);
  return {
    fields,
    buttons,
    title: document.title || "",
    url: location.href,
    text: (document.body ? document.body.innerText : "").slice(0, 4000),
  };
}
"""


def _same_site(candidate: str, base: str) -> bool:
    try:
        left = urllib.parse.urlparse(candidate)
        right = urllib.parse.urlparse(base)
    except ValueError:
        return False
    if left.scheme not in ("http", "https"):
        return False
    return left.netloc.lower().removeprefix("www.") == right.netloc.lower().removeprefix("www.")


def _candidate_links(page: Any, base: str) -> list[tuple[str, str]]:
    """Links of the page that may lead to a submission form or profile."""
    try:
        anchors = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(el => ({href: el.href, text: (el.innerText || '').trim()}))",
        )
    except Exception:
        return []
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in anchors or []:
        href = str(anchor.get("href") or "")
        text = str(anchor.get("text") or "")
        if not href or href in seen:
            continue
        if not _same_site(href, base):
            continue
        lowered = f"{href} {text}".lower()
        if any(word in lowered for word in _TARGET_WORDS):
            found.append((href, text))
            seen.add(href)
    return found[:MAX_CANDIDATES]


def _common_paths(base: str) -> list[tuple[str, str]]:
    parsed = urllib.parse.urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return [(f"{origin}{path}", path.strip("/")) for path in _TARGET_PATHS]


def _inspect(page: Any, url: str, link_text: str) -> dict[str, Any] | None:
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        page.wait_for_timeout(700)
    except Exception:
        return None
    if response is not None and response.status >= 400:
        return None
    try:
        data = page.evaluate(_COLLECT_JS)
    except Exception:
        return None
    fields = data.get("fields") or []
    body = str(data.get("text") or "")
    if any(marker in body.lower() for marker in _LOGIN_MARKERS) and not fields:
        return None
    score, reasons = score_page(
        url=str(data.get("url") or url),
        title=str(data.get("title") or ""),
        link_text=link_text,
        fields=fields,
        has_submit=bool(data.get("buttons")),
        body_text=body,
    )
    if score < FOUND_AT:
        return None
    return {
        "url": str(data.get("url") or url),
        "confidence": score,
        "fields": fields,
        "buttons": data.get("buttons") or [],
        "reasons": reasons,
    }


def discover(
    context: Any,
    website: Any,
    *,
    start_url: str | None = None,
    extra_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Walk an authenticated browser and return the best backlink target.

    ``extra_urls`` are the internal pages the site inspection already ranked
    (profile editor, submission page, forum ...).  They are tried right after
    the current page, before generic guesses.
    """
    base = (
        (start_url or "").strip()
        or str(getattr(website, "opportunity_url", "") or "").strip()
        or str(getattr(website, "domain", "") or "").strip()
    )
    if base and not base.startswith(("http://", "https://")):
        base = "https://" + base
    if not base:
        return {"found": False, "url": None, "confidence": 0, "fields": [], "reasons": ["No URL is known."]}
    try:
        page = context.new_page()
    except Exception as exc:  # pragma: no cover - browser already gone
        return {"found": False, "url": None, "confidence": 0, "fields": [], "reasons": [str(exc)]}
    try:
        try:
            page.goto(base, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(900)
        except Exception as exc:
            return {"found": False, "url": None, "confidence": 0, "fields": [], "reasons": [f"The site could not be opened: {exc}"]}

        candidates: list[tuple[str, str]] = [(base, "current page")]
        for url in extra_urls or []:
            url = (url or "").strip()
            if url:
                candidates.append((url, "ranked by site inspection"))
        candidates.extend(_candidate_links(page, base))
        candidates.extend(_common_paths(base))

        best: dict[str, Any] | None = None
        seen: set[str] = set()
        checked = 0
        for url, link_text in candidates:
            if url in seen:
                continue
            seen.add(url)
            if checked >= MAX_INSPECT:
                break
            if not _same_site(url, base):
                continue
            checked += 1
            result = _inspect(page, url, link_text)
            if result is None:
                continue
            if best is None or result["confidence"] > best["confidence"]:
                best = result
            if result["confidence"] >= 80:
                break
        if best is None:
            return {
                "found": False,
                "url": None,
                "confidence": 0,
                "fields": [],
                "reasons": ["No page with a link or profile field was found while logged in."],
                "checked": checked,
            }
        return {"found": True, **best, "checked": checked}
    finally:
        with suppress(Exception):
            page.close()


def payload(result: dict[str, Any]) -> dict[str, Any]:
    """The part of a discovery result that is stored on the row."""
    return {
        "backlink_url": result.get("url"),
        "backlink_form": {
            "fields": result.get("fields") or [],
            "buttons": result.get("buttons") or [],
            "reasons": result.get("reasons") or [],
        },
        "backlink_confidence": int(result.get("confidence") or 0),
        "found": bool(result.get("found")),
    }


__all__ = ["FOUND_AT", "discover", "payload", "score_page"]
