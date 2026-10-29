"""Post the backlink from the account a batch just created.

The account flow leaves a real, logged-in browser and the page that carries a
link field (a profile editor, an "add listing" form, a forum's new thread, a
comment box ...).  This module fills that form with the business values and
submits it - and it only reports a link when it could observe one:

* the page already shows the target link -> ``VERIFIED``,
* the site confirmed the submission (success text, URL change) but the link is
  not public yet (moderation) -> ``POSTED``,
* the form needs a human (CAPTCHA, login wall, unknown required field) ->
  ``NEEDS_HUMAN`` with the exact reason,
* nothing was submitted because no link field exists -> ``NEEDS_HUMAN`` too:
  the row keeps the page so the operator can open it and see why.

The module is deliberately pure where it can be: the field classifier and the
value builder are testable without a browser.
"""

from __future__ import annotations

import re
import urllib.parse
from contextlib import suppress
from typing import Any

STATUS_NONE = "NONE"
STATUS_POSTED = "POSTED"
STATUS_VERIFIED = "VERIFIED"
STATUS_NEEDS_HUMAN = "NEEDS_HUMAN"
STATUS_FAILED = "FAILED"

#: Words a page shows when a submission was accepted but not published yet.
_APPROVAL_WORDS = (
    "awaiting approval",
    "pending approval",
    "waiting for approval",
    "under review",
    "will be reviewed",
    "moderation",
    "submitted successfully",
    "successfully submitted",
    "thank you for your submission",
    "thanks for your submission",
    "your listing has been added",
    "profile updated",
    "saved successfully",
    "changes saved",
)

#: Words that prove the form was rejected / needs a human instead.
_REJECTION_WORDS = (
    "captcha",
    "not a robot",
    "verify you are human",
    "incorrect",
    "invalid",
    "already been taken",
    "already exists",
    "error",
)

#: Text of links that open the public page of the posted entry.
_PUBLIC_LINK_WORDS = (
    "view profile",
    "my profile",
    "public profile",
    "view listing",
    "view your listing",
    "view post",
    "see your post",
    "view page",
)

_LOGIN_WORDS = (
    "sign in to continue",
    "log in to continue",
    "please sign in",
    "please log in",
    "login required",
    "you must be logged in",
)

_LINK_TOKENS = (
    "url",
    "website",
    "web site",
    "homepage",
    "home page",
    "web address",
    "site address",
    "domain",
    "link",
)
_ANCHOR_TOKENS = ("anchor", "link text", "text of the link")
_CONTENT_TOKENS = (
    "description",
    "about",
    "bio",
    "content",
    "message",
    "comment",
    "body",
    "details",
    "summary",
    "text",
)
_TITLE_TOKENS = ("title", "headline", "subject")
_NAME_TOKENS = (
    "business name",
    "company",
    "organisation",
    "organization",
    "display name",
    "your name",
    "full name",
    "name",
)
_EMAIL_TOKENS = ("email", "e-mail", "e mail")
_PHONE_TOKENS = ("phone", "mobile", "telephone", "contact number", "whatsapp")
_ADDRESS_TOKENS = ("address", "street")
_CITY_TOKENS = ("city", "town")
_ZIP_TOKENS = ("zip", "postal", "postcode")
_COUNTRY_TOKENS = ("country", "nation")
_CATEGORY_TOKENS = ("category", "categories", "industry", "sector", "niche")
_TERMS_TOKENS = ("agree", "terms", "privacy", "consent", "accept")


def _norm(field: dict[str, Any]) -> str:
    raw = " ".join(
        str(field.get(key) or "")
        for key in (
            "name",
            "id",
            "placeholder",
            "label",
            "autocomplete",
            "aria",
            "title",
        )
    ).lower()
    text = re.sub(r"[_\-\[\]]+", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def field_role(field: dict[str, Any]) -> str:
    """What a submission field asks for (or ``""`` when it is unknown)."""
    text = _norm(field)
    kind = str(field.get("type") or "").lower()
    tag = str(field.get("tag") or "").lower()
    if not text and kind not in ("email", "url", "tel"):
        return ""
    if kind == "email" or any(token in text for token in _EMAIL_TOKENS):
        return "email"
    if kind == "tel" or any(token in text for token in _PHONE_TOKENS):
        return "phone"
    if any(token in text for token in _ANCHOR_TOKENS):
        return "anchor"
    if kind == "url" or any(token in text for token in _LINK_TOKENS):
        # "Website name" is a name, not the URL of the website.
        if "name" in text and not any(
            token in text for token in ("url", "link", "address")
        ):
            return "name"
        return "link"
    if any(token in text for token in _CONTENT_TOKENS):
        return "description"
    if any(token in text for token in _TITLE_TOKENS):
        return "title"
    if any(token in text for token in _CATEGORY_TOKENS):
        return "category"
    if any(token in text for token in _COUNTRY_TOKENS):
        return "country"
    if any(token in text for token in _ZIP_TOKENS):
        return "zip"
    if any(token in text for token in _CITY_TOKENS):
        return "city"
    if any(token in text for token in _ADDRESS_TOKENS):
        return "address"
    if any(token in text for token in _NAME_TOKENS):
        return "name"
    if kind in ("checkbox", "radio") and any(
        token in text for token in _TERMS_TOKENS
    ):
        return "terms"
    if any(token in text for token in _TERMS_TOKENS):
        return "terms"
    del tag
    return ""


def build_values(
    project: Any, website: Any, row: Any, *, landing_url: str = ""
) -> dict[str, str]:
    """The values a submission form can ask for, from the business profile."""
    profile = getattr(project, "business_profile", None)
    name = str(getattr(profile, "name", "") or getattr(project, "name", "") or "").strip()
    landing = (
        landing_url
        or str(getattr(profile, "primary_website", "") or "").strip()
        or str(getattr(project, "target_website", "") or "").strip()
    )
    descriptions = list(getattr(profile, "business_descriptions", None) or [])
    description = str(getattr(website, "description", "") or "").strip() or (
        str(descriptions[0]).strip() if descriptions else ""
    )
    if not description:
        description = str(getattr(profile, "description", "") or "").strip()
    anchors = list(getattr(profile, "preferred_anchors", None) or [])
    anchor = str(getattr(website, "anchor_text", "") or "").strip() or (
        str(anchors[0]).strip() if anchors else name
    )
    countries = list(getattr(profile, "target_countries", None) or [])
    categories = list(getattr(profile, "preferred_categories", None) or [])
    return {
        "link": landing,
        "anchor": anchor or landing,
        "title": anchor or name,
        "description": description,
        "name": name,
        "company": name,
        "email": str(getattr(row, "email", "") or "").strip(),
        "phone": str(getattr(profile, "contact_phone", "") or "").strip(),
        "address": "",
        "city": "",
        "zip": "",
        "country": str(countries[0]).strip() if countries else "",
        "category": str(categories[0]).strip() if categories else "",
        "terms": "1",
    }


def linked_on_page(html: str, landing_url: str) -> bool:
    """Does the page carry a real link to the target website?"""
    if not landing_url:
        return False
    parsed = urllib.parse.urlparse(landing_url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if not host:
        return False
    text = html or ""
    for match in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", text, re.I):
        href = match.group(1)
        if host in href.lower():
            return True
    return False


#: Collect the visible controls and the surrounding signals of a page.
_COLLECT_JS = r"""
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && box.width > 1 && box.height > 1;
  };
  const labelFor = (el) => {
    const parts = [];
    if (el.labels) for (const label of el.labels) parts.push(label.innerText || '');
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      for (const id of labelledBy.split(/\s+/)) {
        const node = document.getElementById(id);
        if (node) parts.push(node.innerText || '');
      }
    }
    if (el.closest('label')) parts.push(el.closest('label').innerText || '');
    const row = el.closest('tr, .field, .form-group, .control');
    if (!parts.length && row) {
      const label = row.querySelector('label, .label, .control-label');
      if (label) parts.push(label.innerText || '');
    }
    return parts.join(' ').replace(/\s+/g, ' ').trim().slice(0, 160);
  };
  const selectorFor = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const name = el.getAttribute('name');
    if (name) return el.tagName.toLowerCase() + '[name="' + CSS.escape(name) + '"]';
    return null;
  };
  const fields = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(
    "input, textarea, select, [contenteditable='true'], [role='combobox']"
  )) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : tag)).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'file', 'image', 'password'].includes(type)) continue;
    const selector = selectorFor(el);
    if (!selector || seen.has(selector)) continue;
    seen.add(selector);
    fields.push({
      selector, tag, type,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      aria: el.getAttribute('aria-label') || '',
      title: el.getAttribute('title') || '',
      label: labelFor(el),
      required: el.required === true || el.getAttribute('aria-required') === 'true',
    });
  }
  const buttons = [];
  for (const el of document.querySelectorAll(
    "button, input[type='submit'], [role='button']"
  )) {
    if (!visible(el)) continue;
    if (el.getAttribute('aria-disabled') === 'true' || el.disabled) continue;
    const text = (el.innerText || el.value || '').trim();
    if (!text || text.length > 60) continue;
    buttons.push({ text, type: el.getAttribute('type') || '' });
  }
  return {
    fields,
    buttons,
    title: document.title || '',
    url: location.href,
    text: document.body ? document.body.innerText.slice(0, 8000) : '',
  };
}
"""

#: Click the public page of the entry the operator just posted (best effort).
_OPEN_PUBLIC_JS = r"""
(words) => {
  for (const el of document.querySelectorAll('a[href]')) {
    const text = (el.innerText || '').trim().toLowerCase();
    if (!text || text.length > 40) continue;
    if (words.some((word) => text.includes(word))) return el.href;
  }
  return '';
}
"""


def collect(root: Any) -> dict[str, Any]:
    """Read the controls of the current page (empty dict when it is gone)."""
    with suppress(Exception):
        data = root.evaluate(_COLLECT_JS)
        if isinstance(data, dict):
            return data
    return {}


def _link_root(page: Any, data: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """The page itself or the iframe that really carries the link field."""
    roles = {field_role(field) for field in data.get("fields") or []}
    if "link" in roles:
        return page, data
    with suppress(Exception):
        for frame in page.frames:
            with suppress(Exception):
                if frame is page.main_frame:
                    continue
            candidate = collect(frame)
            if "link" in {field_role(field) for field in candidate.get("fields") or []}:
                return frame, candidate
    return page, data


def _linked_anywhere(page: Any, landing_url: str) -> str:
    """The URL of the page/frame that already shows the link (or ``""``)."""
    with suppress(Exception):
        if linked_on_page(page.content(), landing_url):
            return str(page.url or "")
    with suppress(Exception):
        for frame in page.frames:
            with suppress(Exception):
                if linked_on_page(frame.content(), landing_url):
                    return str(frame.url or page.url or "")
    return ""


def _submit_button(page: Any, data: dict[str, Any]) -> bool:
    """Click the most likely submit button of the form."""
    for wanted in (
        "save changes",
        "save",
        "submit",
        "publish",
        "post",
        "add listing",
        "update",
        "send",
        "create",
    ):
        with suppress(Exception):
            locator = page.get_by_role(
                "button", name=re.compile(re.escape(wanted), re.IGNORECASE)
            ).first
            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=6000)
                return True
    del data
    with suppress(Exception):
        page.click("button[type=submit], input[type=submit]", timeout=6000)
        return True
    with suppress(Exception):
        page.keyboard.press("Enter")
        return True
    return False


def _already_linked(page: Any, landing_url: str) -> bool:
    return bool(_linked_anywhere(page, landing_url))


def post(
    page: Any,
    *,
    target_url: str,
    values: dict[str, str],
    challenge: Any = None,
    timeout_ms: int = 25_000,
) -> dict[str, Any]:
    """Fill the form on ``target_url`` and submit it.

    ``page`` is the logged-in tab of the project browser.  ``challenge`` is a
    callable that returns ``"CAPTCHA"`` when the page asks for a human; it is
    passed in so this module never needs the sign-up internals.
    """
    target_url = (target_url or "").strip()
    if not target_url:
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": "No page with a link field is known for this website.",
            "reasons": ["no target URL"],
        }
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
    except Exception as exc:
        return {
            "status": STATUS_FAILED,
            "published_url": None,
            "message": f"The page could not be opened: {exc}",
            "reasons": ["navigation failed"],
        }

    if callable(challenge) and challenge() == "CAPTCHA":
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": "A CAPTCHA guards the submission form. Solve it once in the live browser, then retry.",
            "reasons": ["captcha"],
        }

    # A profile page often shows the link already: no second submission.
    already = _linked_anywhere(page, values.get("link", ""))
    if already:
        return {
            "status": STATUS_VERIFIED,
            "published_url": already,
            "message": "The live page already carries the link - nothing was submitted again.",
            "reasons": ["link found on the page"],
        }

    data = collect(page)
    interact, data = _link_root(page, data)
    fields = list(data.get("fields") or [])
    text = str(data.get("text") or "").lower()
    if not fields:
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": (
                "The page has no form to post a link. Open it once and check "
                "whether the site offers a profile / listing editor."
            ),
            "reasons": ["no form fields"],
        }
    if any(word in text for word in _LOGIN_WORDS):
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": "The site asked for a login on the submission page - sign in once, then retry.",
            "reasons": ["login wall"],
        }

    roles: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        role = field_role(field)
        if role:
            roles.setdefault(role, []).append(field)
    if not roles.get("link"):
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": (
                "The page has no website / URL field, so the link cannot be "
                "placed here. Open the page once and use the site's own "
                "profile or listing editor."
            ),
            "reasons": ["no link field"],
        }

    # Terms first: some forms disable the submit button until they are checked.
    for term in roles.get("terms", []):
        if str(term.get("type")) in ("checkbox", "radio"):
            with suppress(Exception):
                interact.check(term["selector"], timeout=4000)

    filled: dict[str, str] = {}
    for role in (
        "link",
        "anchor",
        "title",
        "name",
        "company",
        "category",
        "country",
        "city",
        "zip",
        "address",
        "description",
        "email",
        "phone",
    ):
        value = values.get(role) or ""
        if not value:
            continue
        if role in ("email", "phone") and not any(
            bool(field.get("required")) for field in roles.get(role, [])
        ):
            # A public profile does not need the address / phone unless the
            # form insists on it.
            continue
        for field in roles.get(role, []):
            kind = str(field.get("type") or "").lower()
            if kind in ("checkbox", "radio", "file", "hidden"):
                continue
            with suppress(Exception):
                if kind == "select" or str(field.get("tag")) == "select":
                    chosen = _select_option(interact, field["selector"], value)
                    if not chosen:
                        continue
                else:
                    interact.fill(field["selector"], value, timeout=6000)
                filled[role] = value
                break

    missing = []
    for field in fields:
        if not field.get("required"):
            continue
        kind = str(field.get("type") or "").lower()
        if kind in ("checkbox", "radio"):
            continue
        role = field_role(field)
        if role and filled.get(role):
            continue
        missing.append(str(field.get("label") or field.get("name") or role or "field")[:60])
    if missing:
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": (
                "These required fields could not be filled by the app: "
                + ", ".join(missing[:6])
                + ". Open the page, type them by hand, then retry."
            ),
            "reasons": ["required fields"],
        }

    before = str(page.url or "")
    pages_before: set[int] = set()
    with suppress(Exception):
        pages_before = {id(item) for item in page.context.pages}
    if not _submit_button(interact, data):
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": "The form has no submit button the app can press. Finish it by hand.",
            "reasons": ["no submit button"],
        }
    page.wait_for_timeout(5000)

    # Some forms open the saved entry in a second tab: follow it.
    with suppress(Exception):
        for item in page.context.pages:
            if id(item) in pages_before:
                continue
            with suppress(Exception):
                item.wait_for_load_state("domcontentloaded", timeout=8000)
            page = item
            break

    if callable(challenge) and challenge() == "CAPTCHA":
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": "A CAPTCHA appeared after submitting the form. Solve it once, then retry.",
            "reasons": ["captcha after submit"],
        }

    after_text = ""
    with suppress(Exception):
        after_text = str(
            interact.evaluate("() => (document.body ? document.body.innerText : '')")
        ).lower()
    public_url = ""
    with suppress(Exception):
        public_url = str(page.evaluate(_OPEN_PUBLIC_JS, list(_PUBLIC_LINK_WORDS)) or "")
    if public_url:
        with suppress(Exception):
            page.goto(public_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1200)

    live = _linked_anywhere(page, values.get("link", ""))
    if live:
        return {
            "status": STATUS_VERIFIED,
            "published_url": live,
            "message": "The link is live on the public page.",
            "reasons": ["link found after submit"],
        }

    accepted = any(word in after_text for word in _APPROVAL_WORDS)
    failed = any(word in after_text for word in _REJECTION_WORDS) and not accepted
    if accepted or (str(page.url or "") != before):
        return {
            "status": STATUS_POSTED,
            "published_url": str(page.url or "") if str(page.url or "") != before else before,
            "message": (
                "Submitted - the site accepted it. The public page does not show "
                "the link yet (moderation?), so it is not called verified."
            ),
            "reasons": ["success signal"],
        }
    if failed:
        screenshot = _screenshot(page)
        return {
            "status": STATUS_NEEDS_HUMAN,
            "published_url": None,
            "message": "The site rejected the submission. Open the page once and check the message.",
            "reasons": ["rejected"],
            "evidence": {"screenshot": screenshot},
        }
    screenshot = _screenshot(page)
    return {
        "status": STATUS_NEEDS_HUMAN,
        "published_url": str(page.url or "") or None,
        "message": (
            "The form was sent but no success signal appeared. Check the page "
            "once; if the entry exists, the link is there."
        ),
        "reasons": ["no success signal"],
        "evidence": {"screenshot": screenshot, "before_url": before},
    }


def _select_option(page: Any, selector: str, value: str) -> bool:
    """Select the option that matches the value (text or value)."""
    options: list[dict[str, str]] = []
    with suppress(Exception):
        options = page.evaluate(
            "(sel) => Array.from(document.querySelectorAll(sel + ' option'))"
            ".map((o) => ({value: o.value, text: (o.innerText || '').trim()}))",
            selector,
        ) or []
    wanted = value.strip().lower()
    chosen = None
    for option in options:
        text = option["text"].lower()
        if wanted and (wanted == text or wanted in text or text in wanted):
            chosen = option
            break
    if chosen is None:
        for option in options:
            if option["value"] and not re.search(
                r"select|choose|please|^-+$", option["text"], re.I
            ):
                chosen = option
                break
    if chosen is None:
        return False
    with suppress(Exception):
        page.select_option(selector, value=chosen["value"])
        return True
    return False


def _screenshot(page: Any) -> str | None:
    """A screenshot path is useful evidence; it must never break the posting."""
    with suppress(Exception):
        from app.core.config import settings

        directory = settings.managed_files_dir / "evidence"
        directory.mkdir(parents=True, exist_ok=True)
        name = "backlink-post-" + str(abs(hash(str(page.url))))[:12] + ".png"
        target = directory / name
        page.screenshot(path=str(target))
        return str(target)
    return None


__all__ = [
    "STATUS_FAILED",
    "STATUS_NEEDS_HUMAN",
    "STATUS_NONE",
    "STATUS_POSTED",
    "STATUS_VERIFIED",
    "build_values",
    "collect",
    "field_role",
    "linked_on_page",
    "post",
]
