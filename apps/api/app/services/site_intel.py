"""Read a website before acting on it.

Guessing ``/register`` and ``/signup`` on every site is slow and often wrong.
This module inspects the page that is already open - its forms, its links, its
inline JavaScript and the JavaScript bundles it loads - and answers the three
questions that decide what the batch has to do:

* **What is this site?**  WordPress, Discourse, XenForo, phpBB, Joomla,
  Drupal, Shopify, Ghost, Webflow, Wix, Squarespace or a custom build.  The
  signature comes from the resources the page really loaded, not from the
  domain name.
* **Where is its sign-up?**  The URL of a form / link / route that the site's
  own code mentions (``registerPath: "/register"``, a ``Sign up`` link, a
  ``/wp-login.php?action=register`` default, ...).  Every candidate is read
  from the code, so it is usually tried first and found in one step.
* **Can a link be placed without an account?**  An anonymous form that already
  carries a URL / website field (a guest comment form, a public submission
  form) is the fastest backlink of all - no sign-up needed.

The analysis is pure Python on a snapshot, so it is fully testable without a
browser; only :func:`inspect` touches the page.
"""

from __future__ import annotations

import re
import urllib.parse
from contextlib import suppress
from typing import Any

from app.services import backlink_post

#: Words a page uses when it only lets signed-in visitors do something.
_LOGIN_WALL_WORDS = (
    "must be logged in",
    "you must log in",
    "please log in to",
    "please sign in to",
    "login required",
    "sign in to continue",
    "log in to continue",
    "sign in to post",
    "log in to post",
    "sign in to submit",
    "log in to submit",
    "sign in to comment",
    "log in to comment",
    "members only",
)

#: A sign-up link / button, in the languages the batch sees most.
_SIGNUP_TEXT = re.compile(
    r"(sign\s*up|signup|register|registration|create\s+(an\s+|a\s+)?(new\s+)?account|"
    r"join|become\s+a\s+member|get\s+started|registr|anmeld|inscri|cadastr|"
    r"criar\s+conta|crear\s+cuenta|s'inscrire|créer\s+un\s+compte|konto\s+erstellen|注册|登録)",
    re.I,
)
_SIGNUP_HREF = re.compile(
    r"(signup|sign-up|register|registration|/join|create-account|create_account|"
    r"/account/create|/user/create|/users/create|"
    r"registr|anmeld|inscri|cadastr|wp-login\.php\?action=register|"
    r"option=com_users|/user/register|/account/register|/users/sign_up)",
    re.I,
)
#: Links that only look like a sign-up (newsletter, event, coupon ...).
_NOT_SIGNUP = re.compile(
    r"(newsletter|subscribe|coupon|deal|event|webinar|waitlist|waiting list|"
    r"mailing list|follow us|donate|volunteer|affiliate)",
    re.I,
)
_LOGIN_TEXT = re.compile(r"(log\s*in|sign\s*in|login|signin|member\s+login|anmelden)", re.I)
_LOGIN_HREF = re.compile(
    r"(/login|/signin|/sign-in|/log-in|/account/login|/users/sign_in|wp-login\.php)(?!\?action=register)",
    re.I,
)

#: The sign-up entry point a platform always has (used when the page is quiet).
PLATFORM_SIGNUP = {
    "wordpress": ["/wp-login.php?action=register"],
    "discourse": ["/signup"],
    "xenforo": ["/register/"],
    "phpbb": ["/ucp.php?mode=register"],
    "joomla": ["/index.php?option=com_users&view=registration"],
    "drupal": ["/user/register"],
    "shopify": ["/account/register"],
    "ghost": ["/signup/"],
    "hubspot": ["/signup"],
}

PLATFORM_LOGIN = {
    "wordpress": ["/wp-login.php"],
    "discourse": ["/login"],
    "xenforo": ["/login/"],
    "phpbb": ["/ucp.php?mode=login"],
    "joomla": ["/index.php?option=com_users&view=login"],
    "drupal": ["/user/login"],
    "shopify": ["/account/login"],
    "ghost": ["/signin/"],
}

#: How a platform looks in the resources / markup it really loaded.
_PLATFORM_SIGNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wordpress", ("wp-content", "wp-includes", "wp-json", "wp-login.php", "/xmlrpc.php")),
    ("discourse", ("discourse", "/session/csrf", "discourse-cdn")),
    ("xenforo", ("xenforo", "/js/xf/", "data-xf-init")),
    ("phpbb", ("phpbb", "ucp.php", "styles/prosilver")),
    ("joomla", ("/media/system/js/", "option=com_users", "com_content")),
    ("drupal", ("/sites/default/files/", "drupal-settings-json", "/core/misc/drupal")),
    ("shopify", ("cdn.shopify.com", "shopify.theme", "/cart.js")),
    ("ghost", ("ghost/api", "ghost.org/", "/assets/built/")),
    ("webflow", ("webflow.js", "assets.website-files.com", "data-wf-page")),
    ("wix", ("wixstatic.com", "wix-code", "parastorage.com")),
    ("squarespace", ("squarespace.com", "static1.squarespace.com")),
    ("hubspot", ("hs-scripts.com", "hubspot.com/", "hsforms")),
    ("blogger", ("blogger.com", "blogspot.com")),
    ("medium", ("medium.com", "cdn-client.medium.com")),
)

#: A route the site's own JavaScript mentions, e.g. ``registerPath: "/register"``.
_SCRIPT_ROUTE = re.compile(
    r"""["'`](https?://[^"'`\s]{4,200}|/[^"'`\s]{1,120})["'`]""",
)
_API_ROUTE = re.compile(
    r"""["'`](/(?:wp-json|api|graphql|ajax|rest)[^"'`\s]{0,140})["'`]""", re.I
)
_LINK_FIELD = re.compile(
    r"(^|[^a-z])(url|web\s*site|website|home\s*page|homepage|site\s*url|link|domain)"
    r"([^a-z]|$)",
    re.I,
)
_SEARCH_FIELD = re.compile(r"(^|\s)(s|q|query|search|keywords?|k)(\s|$)", re.I)
_NOT_DIRECT = re.compile(
    r"(newsletter|subscribe|mailchimp|sendgrid|hubspot|contact\s*form|search|"
    r"login|sign\s*in|password|checkout|cart|payment)",
    re.I,
)
_SKIP_ROUTES = re.compile(
    r"(newsletter|subscribe|coupon|event|webinar|waitlist|affiliate|donate|"
    r"contact|search|privacy|terms|policy|sitemap)",
    re.I,
)

_MAX_SIGNUP = 12
_MAX_LOGIN = 6
_MAX_API = 10


# --------------------------------------------------------------------------
# Reading the page
# --------------------------------------------------------------------------

#: Everything the analysis needs, read in one call.
_SNAPSHOT_JS = r"""
() => {
  const abs = (value) => {
    try { return new URL(value, location.href).href; } catch (e) { return ''; }
  };
  const label = (el) => ((el.innerText || el.value || '') + '')
    .replace(/\s+/g, ' ').trim().slice(0, 100);
  const skip = ['hidden', 'submit', 'button', 'image', 'reset', 'file'];
  const fieldsOf = (root) => Array.from(root.querySelectorAll('input, textarea, select'))
    .filter((el) => !skip.includes((el.getAttribute('type') || '').toLowerCase()))
    .map((el) => ({
      name: (el.getAttribute('name') || '').slice(0, 80),
      type: (el.getAttribute('type') || el.tagName || '').toLowerCase(),
      placeholder: (el.getAttribute('placeholder') || '').slice(0, 80),
    }))
    .slice(0, 40);
  const forms = [];
  for (const form of document.querySelectorAll('form, [role=form]')) {
    forms.push({
      action: abs(form.getAttribute('action') || ''),
      method: (form.getAttribute('method') || 'get').toLowerCase(),
      id: (form.id || '').slice(0, 80),
      cls: String(form.className || '').slice(0, 120),
      fields: fieldsOf(form),
    });
    if (forms.length >= 40) break;
  }
  const links = [];
  for (const el of document.querySelectorAll('a[href]')) {
    const href = abs(el.getAttribute('href'));
    if (!href || href.indexOf('javascript:') === 0) continue;
    links.push({ text: label(el), href });
    if (links.length >= 500) break;
  }
  const buttons = [];
  for (const el of document.querySelectorAll('button, [role=button]')) {
    const text = label(el);
    if (!text) continue;
    buttons.push({ text, type: (el.getAttribute('type') || '').toLowerCase() });
    if (buttons.length >= 120) break;
  }
  const scripts = Array.from(document.scripts)
    .map((script) => (script.src ? abs(script.src) : ''))
    .filter(Boolean)
    .slice(0, 15);
  const inline = Array.from(document.scripts)
    .filter((script) => !script.src)
    .map((script) => script.textContent || '')
    .join('\n')
    .slice(0, 120000);
  const resources = [];
  for (const entry of performance.getEntriesByType('resource')) {
    resources.push(entry.name);
    if (resources.length >= 140) break;
  }
  return {
    url: location.href,
    title: document.title || '',
    generator: ((document.querySelector('meta[name=generator]') || {}).content) || '',
    lang: document.documentElement.lang || '',
    forms, links, buttons, scripts, inline, resources,
    bodyText: document.body ? document.body.innerText.slice(0, 7000) : '',
  };
}
"""

#: Read the JavaScript bundles of the site itself (same origin only).
_FETCH_SCRIPTS_JS = r"""
async (urls) => {
  let text = '';
  for (const url of urls) {
    try {
      const response = await fetch(url, { credentials: 'same-origin' });
      if (!response.ok) continue;
      const kind = response.headers.get('content-type') || '';
      if (kind && !/javascript|ecmascript|text\/plain|application\/json/i.test(kind)) continue;
      const body = await response.text();
      text += '\n' + body.slice(0, 250000);
      if (text.length > 600000) break;
    } catch (e) {}
  }
  return text;
}
"""


def _same_origin(url: str, page_url: str) -> bool:
    try:
        left = urllib.parse.urlsplit(url)
        right = urllib.parse.urlsplit(page_url)
    except ValueError:
        return False
    return bool(left.netloc) and left.netloc == right.netloc


def snapshot(page: Any) -> dict[str, Any]:
    """Take the snapshot of the page (empty when the page is already gone)."""
    with suppress(Exception):
        data = page.evaluate(_SNAPSHOT_JS)
        if isinstance(data, dict):
            return data
    return {}


def inspect(page: Any, *, max_scripts: int = 4) -> dict[str, Any]:
    """Read the open page and its own JavaScript, then build the plan."""
    data = snapshot(page)
    if not data:
        return analyze({})
    page_url = str(data.get("url") or "")
    bundles = [
        url
        for url in data.get("scripts") or []
        if _same_origin(str(url), page_url)
    ][:max_scripts]
    script_text = ""
    if bundles:
        with suppress(Exception):
            script_text = str(page.evaluate(_FETCH_SCRIPTS_JS, bundles) or "")
    return analyze(data, script_text=script_text)


# --------------------------------------------------------------------------
# The analysis (pure)
# --------------------------------------------------------------------------


def _platform_haystack(data: dict[str, Any], script_text: str) -> str:
    parts = [
        str(data.get("generator") or ""),
        str(data.get("inline") or ""),
        script_text or "",
        " ".join(str(item) for item in data.get("resources") or []),
        " ".join(str(item) for item in data.get("scripts") or []),
        " ".join(
            str(link.get("href") or "") for link in data.get("links") or []
        ),
    ]
    return " ".join(parts).lower()


def classify_platform(data: dict[str, Any], script_text: str = "") -> tuple[str, list[str]]:
    """What the site is built with, from what the page really loaded."""
    haystack = _platform_haystack(data, script_text)
    generator = str(data.get("generator") or "").lower()
    for name, signs in _PLATFORM_SIGNS:
        found = [sign for sign in signs if sign in haystack or sign in generator]
        if found:
            return name, found
    return "unknown", []


def _clean(url: str, page_url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urllib.parse.urljoin(page_url, url)
    if not url.startswith("http"):
        return ""
    return url


def _route_candidates(
    data: dict[str, Any], script_text: str, page_url: str
) -> list[str]:
    """Routes the page's own code mentions (bundles and inline scripts)."""
    corpus = "\n".join([str(data.get("inline") or ""), script_text or ""])
    if not corpus:
        return []
    found: list[str] = []
    for match in _SCRIPT_ROUTE.finditer(corpus):
        route = match.group(1)
        if not _SIGNUP_HREF.search(route) or _SKIP_ROUTES.search(route):
            continue
        cleaned = _clean(route, page_url)
        if cleaned and cleaned not in found:
            found.append(cleaned)
        if len(found) >= _MAX_SIGNUP:
            break
    return found


def signup_urls(data: dict[str, Any], script_text: str = "", platform: str = "unknown") -> list[str]:
    """Every URL that can open a sign-up form, best first."""
    page_url = str(data.get("url") or "")
    found: list[str] = []

    def add(url: str) -> None:
        cleaned = _clean(url, page_url)
        if not cleaned or cleaned in found:
            return
        if _NOT_SIGNUP.search(cleaned):
            return
        found.append(cleaned)

    # 1. A form whose action already is the registration endpoint.
    for form in data.get("forms") or []:
        action = str(form.get("action") or "")
        if action and _SIGNUP_HREF.search(action):
            add(action)

    # 2. A visible link / tab that says "Sign up" (any language).
    for link in data.get("links") or []:
        text = str(link.get("text") or "")
        href = str(link.get("href") or "")
        if _NOT_SIGNUP.search(text) or not href:
            continue
        by_href = bool(_SIGNUP_HREF.search(href))
        by_text = bool(_SIGNUP_TEXT.search(text))
        if not by_href and not by_text:
            continue
        # A "Sign up" that really opens the login form (no registration tab)
        # is not a registration page.
        if not by_href and _LOGIN_HREF.search(href):
            continue
        if not _SKIP_ROUTES.search(href):
            add(href)

    # 3. A route the site's own JavaScript uses.
    for route in _route_candidates(data, script_text, page_url):
        add(route)

    # 4. The platform's fixed entry point.
    for path in PLATFORM_SIGNUP.get(platform, []):
        add(urllib.parse.urljoin(page_url, path))

    return found[:_MAX_SIGNUP]


def login_urls(data: dict[str, Any], platform: str = "unknown") -> list[str]:
    """The sign-in page of the site, when the page itself shows one."""
    page_url = str(data.get("url") or "")
    found: list[str] = []

    def add(url: str) -> None:
        cleaned = _clean(url, page_url)
        if cleaned and cleaned not in found:
            found.append(cleaned)

    for form in data.get("forms") or []:
        fields = {str(field.get("type") or "") for field in form.get("fields") or []}
        action = str(form.get("action") or "")
        if "password" in fields and action:
            add(action)
    for link in data.get("links") or []:
        href = str(link.get("href") or "")
        text = str(link.get("text") or "")
        if href and (_LOGIN_HREF.search(href) or _LOGIN_TEXT.search(text)):
            add(href)
    for path in PLATFORM_LOGIN.get(platform, []):
        add(urllib.parse.urljoin(page_url, path))
    return found[:_MAX_LOGIN]


def _looks_like_link_field(field: dict[str, Any]) -> bool:
    role = backlink_post.field_role(
        {
            "name": field.get("name") or "",
            "placeholder": field.get("placeholder") or "",
            "type": field.get("type") or "",
        }
    )
    if role == "link":
        return True
    hint = f"{field.get('name') or ''} {field.get('placeholder') or ''}"
    return bool(_LINK_FIELD.search(hint))


def direct_form(data: dict[str, Any]) -> dict[str, Any] | None:
    """An anonymous form that already accepts a link (no account needed)."""
    page_url = str(data.get("url") or "")
    body = str(data.get("bodyText") or "").lower()
    if any(marker in body for marker in _LOGIN_WALL_WORDS):
        return None
    for form in data.get("forms") or []:
        fields = list(form.get("fields") or [])
        if not fields:
            continue
        types = {str(field.get("type") or "").lower() for field in fields}
        if "password" in types:
            continue
        names = " ".join(str(field.get("name") or "") for field in fields)
        if _SEARCH_FIELD.search(names) and "url" not in names.lower():
            continue
        action = str(form.get("action") or "") or page_url
        if not _same_origin(action, page_url):
            continue
        hints = " ".join(
            [
                str(form.get("id") or ""),
                str(form.get("cls") or ""),
                action,
                names,
            ]
        )
        if _NOT_DIRECT.search(hints):
            continue
        link_fields = [
            str(field.get("name") or field.get("placeholder") or "url")
            for field in fields
            if _looks_like_link_field(field)
        ]
        if not link_fields:
            continue
        lowered = hints.lower()
        if "comment" in lowered:
            kind = "comment form"
        elif re.search(r"(submit|add|listing|post|classified|directory)", lowered):
            kind = "public submission form"
        elif re.search(r"(profile|account|settings)", lowered):
            kind = "profile editor"
        else:
            kind = "anonymous form"
        return {
            "url": page_url,
            "action": action,
            "method": str(form.get("method") or "get"),
            "fields": link_fields,
            "kind": kind,
        }
    return None


def api_routes(script_text: str) -> list[str]:
    """The API endpoints the site's own code mentions (for the report)."""
    found: list[str] = []
    for match in _API_ROUTE.finditer(script_text or ""):
        route = match.group(1)
        if (
            route.startswith("/wp-json")
            or route.startswith("/api")
            or route.startswith("/graphql")
        ) and route not in found:
            found.append(route)
        if len(found) >= _MAX_API:
            break
    return found


def plan(intel: dict[str, Any]) -> str:
    """What the batch should do with this site.

    ``SIGNUP`` first (a durable account), ``DIRECT`` when the site has no
    sign-up but does have a public form, ``LOGIN`` when only a sign-in page
    was found and ``NONE`` when the code shows neither.
    """
    if intel.get("signup_urls"):
        return "SIGNUP"
    if intel.get("direct"):
        return "DIRECT"
    if intel.get("login_urls"):
        return "LOGIN"
    return "NONE"


def analyze(data: dict[str, Any], *, script_text: str = "") -> dict[str, Any]:
    """Turn a page snapshot into the decision the batch uses."""
    page_url = str(data.get("url") or "")
    platform, evidence = classify_platform(data, script_text)
    signups = signup_urls(data, script_text, platform)
    logins = login_urls(data, platform)
    direct = direct_form(data)
    result: dict[str, Any] = {
        "url": page_url,
        "title": str(data.get("title") or ""),
        "platform": platform,
        "platform_evidence": evidence,
        "signup_urls": signups,
        "login_urls": logins,
        "direct": direct,
        "api": api_routes(script_text),
        "forms": len(data.get("forms") or []),
        "notes": [],
    }
    result["plan"] = plan(result)
    if platform != "unknown":
        result["notes"].append(
            "The site's own code shows " + ", ".join(evidence[:3]) + "."
        )
    if direct:
        result["notes"].append(
            f"A {direct['kind']} with a link field works without an account."
        )
    elif any(marker in str(data.get("bodyText") or "").lower() for marker in _LOGIN_WALL_WORDS):
        result["notes"].append("The page asks visitors to sign in before posting.")
    if signups:
        result["notes"].append(f"{len(signups)} sign-up path(s) found in the code.")
    return result


# --------------------------------------------------------------------------
# Small helpers for the batch / the report
# --------------------------------------------------------------------------

LABELS = {
    "wordpress": "WordPress",
    "discourse": "Discourse",
    "xenforo": "XenForo",
    "phpbb": "phpBB",
    "joomla": "Joomla",
    "drupal": "Drupal",
    "shopify": "Shopify",
    "ghost": "Ghost",
    "webflow": "Webflow",
    "wix": "Wix",
    "squarespace": "Squarespace",
    "hubspot": "HubSpot",
    "blogger": "Blogger",
    "medium": "Medium",
    "unknown": "unknown",
}


def label(intel: dict[str, Any]) -> str:
    """The platform in words (the report uses it)."""
    platform = str(intel.get("platform") or "unknown")
    return LABELS.get(platform, platform)


def brief(intel: dict[str, Any]) -> dict[str, Any]:
    """The small summary stored on the row (never the whole page)."""
    direct = intel.get("direct") or {}
    return {
        "url": intel.get("url") or "",
        "title": str(intel.get("title") or "")[:200],
        "platform": intel.get("platform") or "unknown",
        "platform_evidence": list(intel.get("platform_evidence") or [])[:5],
        "plan": intel.get("plan") or "NONE",
        "signup_urls": list(intel.get("signup_urls") or [])[:6],
        "login_urls": list(intel.get("login_urls") or [])[:3],
        "api": list(intel.get("api") or [])[:5],
        "direct": (
            {
                "url": direct.get("url"),
                "action": direct.get("action"),
                "kind": direct.get("kind"),
                "fields": list(direct.get("fields") or [])[:5],
            }
            if direct
            else None
        ),
        "notes": list(intel.get("notes") or [])[:5],
    }


def explain(intel: dict[str, Any]) -> str:
    """An honest sentence for the row when nothing could be used."""
    name = label(intel)
    parts: list[str] = []
    if name != "unknown":
        parts.append(f"The page looks like a {name} site")
    else:
        parts.append("The page did not show a sign-up or submission form")
    if intel.get("signup_urls"):
        parts.append(
            "the sign-up paths found in its code ("
            + ", ".join(list(intel["signup_urls"])[:3])
            + ") did not open a form"
        )
    if intel.get("login_urls"):
        parts.append(
            "its login page is " + str(next(iter(intel["login_urls"])))
        )
    return ". ".join(parts).strip(".") + "."


__all__ = [
    "LABELS",
    "PLATFORM_LOGIN",
    "PLATFORM_SIGNUP",
    "analyze",
    "api_routes",
    "brief",
    "classify_platform",
    "direct_form",
    "explain",
    "inspect",
    "label",
    "login_urls",
    "plan",
    "signup_urls",
    "snapshot",
]
