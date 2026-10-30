"""Learn a website's real procedure once, then remember it.

Every backlink website asks its own sequence of steps: create an account,
verify the e-mail with a code or a link, complete a profile, open a submission
page and wait for approval.  Guessing that sequence costs a browser run per
site, so this module reads the site over plain HTTP (fast, no browser) and
stores the result on the website row:

* the **sign-up page** (or that the site has none),
* the **post page** where the link is placed,
* whether Google sign-in is offered,
* which verification the mail carries (code / link / none),
* the ordered **steps** a human sees, so the report can show them.

When the operator pastes the sign-up or post URL while adding the website, that
URL is the first candidate and the probe starts from it: the system trusts the
hint and verifies it instead of guessing.  If no hint is given the links of the
page are ranked with :mod:`app.services.site_intel` and the best candidates are
opened and checked.

Nothing here submits a form or creates an account; it only reads pages, so a
broken or hostile site costs one request, not a browser session.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.net import FetchResult, safe_get
from app.db.models import Website
from app.services import site_intel
from app.services.opportunities import normalize_url

log = get_logger(__name__)

#: Words that mark a link to the submission / post page (mirrors the browser
#: finder so both paths agree on what a post page looks like).
_POST_WORDS = (
    "submit",
    "add your business",
    "add business",
    "add listing",
    "add a listing",
    "add your listing",
    "add website",
    "add your website",
    "add url",
    "add site",
    "get listed",
    "list your",
    "new listing",
    "post ad",
    "post a listing",
    "post your",
    "create listing",
    "submit listing",
    "submit your",
    "write for us",
    "new thread",
    "new topic",
    "create thread",
    "start a thread",
    "edit profile",
    "profile settings",
    "account settings",
    "my profile",
)

#: Generic paths tried when the page links do not name a page.
_FALLBACK_SIGNUP = (
    "/signup",
    "/sign-up",
    "/register",
    "/join",
    "/create-account",
    "/account/register",
    "/users/sign_up",
)
_FALLBACK_POST = (
    "/submit",
    "/add",
    "/add-listing",
    "/submit-listing",
    "/add-your-business",
    "/post",
    "/new",
    "/profile/edit",
)

#: Words that mark a sign-up link in the page navigation.
_SIGNUP_WORDS = (
    "sign up",
    "signup",
    "create account",
    "create an account",
    "create your account",
    "register",
    "join",
    "get started",
    "become a member",
    "start free",
)

#: What a password / e-mail / link field looks like in static HTML.
_EMAIL_INPUT = re.compile(r"type=['\"]email|name=['\"][^'\"]*e-?mail", re.I)
_PASSWORD_INPUT = re.compile(r"type=['\"]password", re.I)
_LINK_INPUT = re.compile(
    r"name=['\"][^'\"]*(url|website|site|link|homepage)|"
    r"placeholder=['\"][^'\"]*(url|website|site|link|homepage)|"
    r"type=['\"]url",
    re.I,
)

#: Mail verification the page promises.
_OTP_WORDS = re.compile(
    r"(one[-\s]?time (code|password)|\botp\b|verification code|6[-\s]?digit|"
    r"six[-\s]?digit|enter the code)",
    re.I,
)
_LINK_WORDS = re.compile(
    r"(confirmation link|verify (your )?(e-?mail|account) by (clicking|following)|"
    r"click the link|activation link|confirm your e-?mail)",
    re.I,
)
_CAPTCHA_WORDS = re.compile(
    r"(recaptcha|hcaptcha|turnstile|cf-challenge|are you a robot|captcha)",
    re.I,
)

#: A URL of an article / blog / news page - never a submission page.
_ARTICLE = re.compile(
    r"(/(news|blog|articles?|stories|story|press|insights?|guides?|resources?|"
    r"discussions?|topics?|questions?|posts?/\d)/|/\d{4}/\d{2}/|\?p=\d+)",
    re.I,
)

#: Sign-up wording on the page itself.
_SIGNUP_HERE = re.compile(
    r"(sign\s*up|signup|register|create (an? )?(new )?account|become a member|join free)",
    re.I,
)

#: A category / catalogue page: it lists entries, it does not take one.
_INDEX_PATH = re.compile(
    r"(/products?/|/catalog/|-catalog/|/manufacturers?/|/suppliers?/)", re.I
)

#: A URL that names a submission / profile page (not a content page).
_POST_PATH = re.compile(
    r"(submit|add[-_/]|listing|get[-_]listed|post[-_/]|new[-_/]|thread|comment|"
    r"profile|edit|dashboard|community|forum)",
    re.I,
)

_MAX_VERIFY = 3
_PROBE_TIMEOUT = 8.0
_PROBE_BUDGET = 30.0


def _clean_text(value: str) -> str:
    return " ".join((value or "").split())[:160]


def _fetch(url: str) -> FetchResult:
    """One SSRF-checked GET (kept small so a probe never reads a whole site)."""
    return safe_get(
        url,
        timeout=_PROBE_TIMEOUT,
        allow_robots=settings.respect_robots,
        max_bytes=800_000,
    )


def page_snapshot(html: str, url: str) -> dict[str, Any]:
    """Turn static HTML into the snapshot :func:`site_intel.analyze` reads."""
    soup = BeautifulSoup(html or "", "lxml")
    links: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True)[:600]:
        href = urljoin(url, anchor.get("href") or "")
        if not href.startswith(("http://", "https://")):
            continue
        links.append({"text": _clean_text(anchor.get_text(" ", strip=True)), "href": href})
    forms: list[dict[str, Any]] = []
    for form in soup.find_all("form")[:40]:
        fields: list[dict[str, str]] = []
        for element in form.find_all(["input", "textarea", "select"])[:40]:
            kind = (element.get("type") or element.name or "text").lower()
            if kind in {"hidden", "submit", "button", "image", "reset", "file"}:
                continue
            fields.append(
                {
                    "name": (element.get("name") or "")[:80],
                    "type": kind,
                    "placeholder": (element.get("placeholder") or "")[:80],
                }
            )
        forms.append(
            {
                "action": urljoin(url, form.get("action") or ""),
                "method": (form.get("method") or "get").lower(),
                "id": (form.get("id") or "")[:80],
                "cls": " ".join(form.get("class") or [])[:120],
                "fields": fields,
            }
        )
    generator = soup.find("meta", attrs={"name": "generator"})
    scripts = [
        urljoin(url, script.get("src") or "")
        for script in soup.find_all("script", src=True)[:15]
    ]
    inline = "\n".join(
        script.get_text() or "" for script in soup.find_all("script", src=False)
    )[:120_000]
    return {
        "url": url,
        "title": _clean_text(soup.title.get_text() if soup.title else ""),
        "generator": (generator.get("content") if generator else "") or "",
        "lang": "",
        "forms": forms,
        "links": links,
        "buttons": [
            {"text": _clean_text(button.get_text(" ", strip=True)), "type": ""}
            for button in soup.find_all("button")[:120]
        ],
        "scripts": scripts,
        "inline": inline,
        "resources": [],
        "iframes": [],
        "bodyText": _clean_text(soup.get_text(" ", strip=True))[:7000],
        "raw": (html or "").lower(),
    }


def page_facts(html: str, url: str) -> dict[str, Any]:
    """What the page itself shows: which fields, which verification, which SSO."""
    raw = (html or "").lower()
    snapshot = page_snapshot(html, url)
    body = str(snapshot.get("bodyText") or "")
    has_password = bool(_PASSWORD_INPUT.search(raw))
    has_email = bool(_EMAIL_INPUT.search(raw)) or bool(
        re.search(r"(e-?mail|username|user\s*name)", body, re.I)
    )
    verification = "unknown"
    if _OTP_WORDS.search(body):
        verification = "otp"
    elif _LINK_WORDS.search(body):
        verification = "link"
    return {
        "snapshot": snapshot,
        "has_email": has_email,
        "has_password": has_password,
        "has_link_field": bool(_LINK_INPUT.search(raw)),
        "signup_form": has_password and has_email,
        "google": bool(
            re.search(r"(accounts\.google\.com|oauth2?/google|google\.com/gsi)", raw)
        ),
        "facebook": bool(re.search(r"(facebook\.com/(dialog/oauth|v[\d.]+))", raw)),
        "verification": verification,
        "captcha": bool(_CAPTCHA_WORDS.search(body + " " + raw[:4000])),
    }


def _ranked(links: list[dict[str, str]], words: tuple[str, ...]) -> list[str]:
    """Same-origin links whose text or href names the wanted page, best first."""
    found: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, link in enumerate(links):
        href = str(link.get("href") or "")
        text = str(link.get("text") or "").lower()
        if not href or href in seen:
            continue
        score = 0
        for position, word in enumerate(words):
            if word in text:
                score = max(score, 100 - position)
            elif word.replace(" ", "-") in href.lower():
                score = max(score, 60 - position)
        if not score:
            continue
        seen.add(href)
        found.append((score, -index, href))
    found.sort(reverse=True)
    return [url for _score, _order, url in found]


def _same_site(url: str, base: str) -> bool:
    return site_intel._same_origin(url, base)


def _dedupe(urls: list[str]) -> list[str]:
    found: list[str] = []
    for url in urls:
        cleaned = (url or "").strip()
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


def probe(
    url: str,
    *,
    signup_hint: str = "",
    post_hint: str = "",
    budget_s: float = _PROBE_BUDGET,
) -> dict[str, Any]:
    """Read the site and name its sign-up page, its post page and its steps.

    The hints (the values the operator pasted) win over every guess.  A hinted
    URL is still opened, so a stale hint is reported instead of trusted.
    """
    started = datetime.now(UTC)
    budget = time.monotonic() + max(2.0, budget_s)
    page_url = normalize_url(url)
    response = _fetch(page_url)
    if response.error or response.status_code >= 400:
        return {
            "checked_at": started.isoformat(),
            "start_url": page_url,
            "reachable": False,
            "error": response.error
            or f"The site answered with HTTP {response.status_code}.",
            "signup_url": signup_hint or "",
            "post_url": post_hint or "",
            "signup_urls": [],
            "post_urls": [],
            "needs_signup": None,
            "steps": [],
            "notes": [],
        }
    final_url = response.final_url or page_url
    facts = page_facts(response.content, final_url)
    intel = site_intel.analyze(facts["snapshot"])

    signup_candidates: list[str] = []
    if signup_hint:
        signup_candidates.append(normalize_url(urljoin(final_url, signup_hint)))
    signup_candidates += [str(item) for item in intel.get("signup_urls") or []]
    signup_candidates += _ranked(facts["snapshot"]["links"], _SIGNUP_WORDS)
    if not signup_candidates:
        signup_candidates += [
            urljoin(final_url, path) for path in _FALLBACK_SIGNUP
        ]
    signup_candidates = _dedupe(
        [item for item in signup_candidates if _same_site(item, final_url)]
    )

    post_candidates: list[str] = []
    if post_hint:
        post_candidates.append(normalize_url(urljoin(final_url, post_hint)))
    post_candidates += [str(item) for item in intel.get("backlink_urls") or []]
    post_candidates += _ranked(facts["snapshot"]["links"], _POST_WORDS)
    if not post_candidates:
        post_candidates += [urljoin(final_url, path) for path in _FALLBACK_POST]
    post_candidates = _dedupe(
        [item for item in post_candidates if _same_site(item, final_url)]
    )

    post_candidates = _dedupe(
        [
            item
            for item in post_candidates
            if not _ARTICLE.search(item) and not _INDEX_PATH.search(item)
        ]
    )

    signup_url, signup_facts, notes, signup_ok = _verify_candidates(
        signup_candidates[:_MAX_VERIFY], kind="signup", base=final_url, budget=budget
    )
    post_url, _post_facts, post_notes, post_ok = _verify_candidates(
        post_candidates[:_MAX_VERIFY + 1], kind="post", base=final_url, budget=budget
    )
    notes += post_notes

    # "No signup" is only claimed when a public form really takes the link;
    # a JavaScript page that hides its form stays "unknown" instead of a
    # confident (and wrong) "no signup needed".
    signup_best = (
        signup_url
        if signup_ok
        else (
            (str((intel.get("signup_urls") or [""])[0]) if intel.get("signup_urls") else "")
            or (signup_candidates[0] if signup_candidates else "")
        )
    )
    post_best = (
        post_url
        if post_ok
        else (
            (str((intel.get("backlink_urls") or [""])[0]) if intel.get("backlink_urls") else "")
            or (post_candidates[0] if post_candidates else "")
        )
    )
    signup_confidence = "verified" if signup_ok else ("candidate" if signup_best else "none")
    post_confidence = "verified" if post_ok else ("candidate" if post_best else "none")
    if signup_hint and not signup_ok:
        signup_confidence = "hint"
    if post_hint and not post_ok:
        post_confidence = "hint"

    if (
        signup_best
        or (facts["has_password"] and facts["has_email"])
        or _SIGNUP_HERE.search(str(facts["snapshot"].get("bodyText") or ""))
    ):
        needs_signup: bool | None = True
    elif intel.get("direct") and not _SIGNUP_HERE.search(
        str(facts["snapshot"].get("bodyText") or "")
    ):
        # A page that offers a public link form *and* no sign-up wording is the
        # only case where "no account needed" is claimed.
        needs_signup = False
    else:
        needs_signup = None
    verification = signup_facts.get("verification") or facts["verification"]
    if verification == "unknown" and signup_facts.get("signup_form"):
        verification = "otp"
    if verification == "unknown" and not needs_signup and intel.get("direct"):
        verification = "none"

    recipe = {
        "checked_at": started.isoformat(),
        "start_url": final_url,
        "reachable": True,
        "platform": intel.get("platform"),
        "platform_evidence": intel.get("platform_evidence") or [],
        # Only a page that really carries the form is stored as *the* URL;
        # a page that merely answered is kept in the candidate list.
        "signup_url": signup_best,
        "signup_confidence": signup_confidence,
        "signup_urls": _dedupe([signup_best, *signup_candidates])[:8],
        "post_url": post_best,
        "post_confidence": post_confidence,
        "post_urls": _dedupe([post_best, *post_candidates])[:8],
        "needs_signup": needs_signup,
        "google": bool(signup_facts.get("google") or facts["google"]),
        "facebook": bool(signup_facts.get("facebook") or facts["facebook"]),
        "verification": verification,
        "captcha": bool(signup_facts.get("captcha") or facts["captcha"]),
        "direct_form": bool(intel.get("direct")),
        "direct_kind": (intel.get("direct") or {}).get("kind") if intel.get("direct") else "",
        "plan": intel.get("plan"),
        "notes": notes,
        "steps": _steps(
            needs_signup=needs_signup,
            google=bool(signup_facts.get("google") or facts["google"]),
            verification=verification,
            direct=bool(intel.get("direct")),
            post_url=post_best,
        ),
    }
    return recipe


def _verify_candidates(
    candidates: list[str], *, kind: str, base: str, budget: float = 0.0
) -> tuple[str, dict[str, Any], list[str], bool]:
    """Open the candidates in order and return the first page that matches.

    A link is only accepted when the live page carries what the step needs: a
    password/e-mail form for a sign-up page, a link/URL field or the words
    "submit" for a post page.  The first reachable page is remembered as the
    fallback, so a JavaScript rendered site still gets a URL instead of none.
    """
    fallback = ""
    notes: list[str] = []
    for url in candidates:
        if budget and time.monotonic() > budget:
            notes.append("The probe ran out of time before every page was read.")
            break
        response = _fetch(url)
        if response.error or response.status_code >= 400:
            notes.append(f"{url} did not answer ({response.error or response.status_code}).")
            continue
        facts = page_facts(response.content, response.final_url or url)
        if not fallback:
            fallback = response.final_url or url
        body = str(facts["snapshot"].get("bodyText") or "").lower()
        if kind == "signup":
            has_form = bool(facts["snapshot"].get("forms"))
            if (
                facts["signup_form"]
                or (facts["has_email"] and re.search(r"(sign\s*up|register|create account)", body))
                or (
                    has_form
                    and re.search(
                        r"(sign\s*up|signup|register|create (an? )?(new )?account|"
                        r"become a member)",
                        body,
                    )
                )
            ):
                return response.final_url or url, facts, notes, True
        else:
            has_form = bool(facts["snapshot"].get("forms"))
            submission = bool(
                re.search(
                    r"(add (your )?(listing|business|website|site)|"
                    r"submit (your )?(listing|url|website|site)|"
                    r"post (a |your )?(listing|ad|comment|thread|article)|"
                    r"new thread|start a thread|edit profile|update profile)",
                    body,
                )
            )
            # A real post page carries a form that takes the link - a blog
            # article that merely mentions "post" does not.
            if has_form and facts["has_link_field"]:
                return response.final_url or url, facts, notes, True
            if (
                has_form
                and submission
                and _POST_PATH.search(response.final_url or url)
            ):
                return response.final_url or url, facts, notes, True
    return fallback, {}, notes, False


def _steps(
    *,
    needs_signup: bool,
    google: bool,
    verification: str,
    direct: bool,
    post_url: str,
) -> list[str]:
    """The procedure in the order a human sees it."""
    steps: list[str] = []
    if needs_signup:
        how = "Continue with Google" if google else "e-mail + password"
        steps.append(f"Create the account ({how}).")
        if verification == "otp":
            steps.append("Verify the e-mail with the code from the project Gmail.")
        elif verification == "link":
            steps.append("Open the confirmation link from the project Gmail.")
        else:
            steps.append("Check the Gmail for a confirmation mail (code or link).")
        steps.append("Complete the profile (name, website, bio) if the site asks.")
    elif direct:
        steps.append("No account: fill the public form with the link.")
    else:
        steps.append("Sign in with the account of this project.")
    if post_url:
        steps.append("Open the post page, fill the link and submit.")
        steps.append("Wait for approval when the site reviews submissions.")
    else:
        steps.append("Find the post page inside the account and submit the link.")
    return steps


def save_recipe(db: Session, website: Website, recipe: dict[str, Any]) -> Website:
    """Store the recipe on the website and fill the empty URL hints."""
    website.recipe = recipe
    if recipe.get("signup_url") and not (website.signup_url or "").strip():
        website.signup_url = str(recipe["signup_url"])[:1000]
    if recipe.get("post_url") and not (website.post_url or "").strip():
        website.post_url = str(recipe["post_url"])[:1000]
    if recipe.get("needs_signup") is not None:
        website.registration_required = bool(recipe["needs_signup"])
    website.last_checked_at = datetime.now(UTC)
    db.commit()
    db.refresh(website)
    return website


def refresh(
    db: Session, website: Website, *, budget_s: float = _PROBE_BUDGET
) -> dict[str, Any]:
    """Probe one website now (hints first) and store the recipe."""
    recipe = probe(
        website.opportunity_url,
        signup_hint=website.signup_url or "",
        post_hint=website.post_url or "",
        budget_s=budget_s,
    )
    save_recipe(db, website, recipe)
    return recipe


def refresh_many(
    db: Session, websites: list[Website], *, workers: int = 4
) -> list[tuple[str, str]]:
    """Probe several websites in parallel and store every recipe."""
    def work(website: Website) -> tuple[str, str]:
        try:
            recipe = probe(
                website.opportunity_url,
                signup_hint=website.signup_url or "",
                post_hint=website.post_url or "",
            )
            save_recipe(db, website, recipe)
            state = "ok" if recipe.get("reachable") else "unreachable"
            return website.id, state
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning(
                "recipe probe failed",
                extra={"extra_fields": {"website": website.id, "error": str(exc)}},
            )
            return website.id, f"error: {exc}"

    results: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for outcome in pool.map(work, websites):
            results.append(outcome)
    return results


def payload(website: Website) -> dict[str, Any] | None:
    """The stored recipe of a website (``None`` before the first probe)."""
    recipe = website.recipe if isinstance(website.recipe, dict) else None
    if not recipe:
        return None
    with suppress(Exception):
        return dict(recipe)
    return None
