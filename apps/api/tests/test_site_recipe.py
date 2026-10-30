"""Tests of the site recipe probe.

The probe reads a website over plain HTTP and stores its procedure: the
sign-up page, the verification the mail carries and the post page.  These
tests use a fake transport, so they describe the decisions, not the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.net import FetchResult
from app.services import site_recipe
from tests.conftest import API


def _result(url: str, html: str, status: int = 200) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status_code=status,
        content=html,
        headers={"content-type": "text/html"},
        elapsed_ms=5,
        redirects=[],
    )


HOME = """
<html><head><title>Pet directory</title></head><body>
  <a href="/signup">Sign up</a>
  <a href="/login">Sign in</a>
  <a href="/add-listing">Add your business</a>
  <p>List your pet business for free.</p>
</body></html>
"""

SIGNUP = """
<html><head><title>Create account</title></head><body>
  <h1>Sign up</h1>
  <form action="/signup" method="post">
    <input type="email" name="email">
    <input type="password" name="password">
    <button>Create account</button>
  </form>
  <p>We send you a one-time code to verify your e-mail.</p>
</body></html>
"""

POST = """
<html><head><title>Add your business</title></head><body>
  <h1>Add your business</h1>
  <form action="/add-listing" method="post">
    <input name="business_name">
    <input name="website" placeholder="https://your-site.com">
    <textarea name="description"></textarea>
    <button>Submit listing</button>
  </form>
</body></html>
"""


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A directory that needs an account, a code and a listing form."""
    pages = {
        "https://directory.example.org/": HOME,
        "https://directory.example.org/signup": SIGNUP,
        "https://directory.example.org/add-listing": POST,
    }

    def fake_get(url: str, **_kwargs: Any) -> FetchResult:
        return _result(url, pages.get(url, "<html><body>Not found</body></html>"), 200)

    monkeypatch.setattr(site_recipe, "safe_get", fake_get)
    return pages


def test_probe_finds_signup_post_and_the_steps(site: dict[str, str]) -> None:
    recipe = site_recipe.probe("https://directory.example.org/")
    assert recipe["reachable"] is True
    assert recipe["signup_url"] == "https://directory.example.org/signup"
    assert recipe["post_url"] == "https://directory.example.org/add-listing"
    assert recipe["post_confidence"] == "verified"
    assert recipe["signup_confidence"] == "verified"
    assert recipe["needs_signup"] is True
    assert recipe["verification"] == "otp"
    assert any("code" in step.lower() for step in recipe["steps"])
    assert any("post page" in step.lower() for step in recipe["steps"])


def test_the_operator_hint_is_used_first(site: dict[str, str]) -> None:
    recipe = site_recipe.probe(
        "https://directory.example.org/",
        signup_hint="https://directory.example.org/signup",
        post_hint="https://directory.example.org/add-listing",
    )
    assert recipe["signup_url"] == "https://directory.example.org/signup"
    assert recipe["post_url"] == "https://directory.example.org/add-listing"


def test_a_dead_site_is_reported_instead_of_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **_kwargs: Any) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=0,
            content="",
            headers={},
            elapsed_ms=1,
            redirects=[],
            error="connection refused",
        )

    monkeypatch.setattr(site_recipe, "safe_get", fake_get)
    recipe = site_recipe.probe("https://dead.example.org/")
    assert recipe["reachable"] is False
    assert recipe["steps"] == []
    assert "connection refused" in recipe["error"]


def test_the_list_shows_the_procedure_and_the_post_page(authenticated_client) -> None:
    created = authenticated_client.post(
        f"{API}/websites",
        json={
            "opportunity_url": "https://directory.example.org/",
            "name": "Pet directory",
            "signup_url": "https://directory.example.org/signup",
            "post_url": "https://directory.example.org/add-listing",
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["signup_url"] == "https://directory.example.org/signup"
    assert row["post_url"] == "https://directory.example.org/add-listing"


def test_the_recipe_endpoint_stores_what_the_probe_read(
    authenticated_client, site: dict[str, str]
) -> None:
    created = authenticated_client.post(
        f"{API}/websites",
        json={
            "opportunity_url": "https://directory.example.org/",
            "name": "Pet directory",
        },
    )
    website_id = created.json()["id"]
    response = authenticated_client.post(f"{API}/websites/{website_id}/recipe")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["needs_signup"] is True
    assert body["signup_url"] == "https://directory.example.org/signup"
    assert body["post_url"] == "https://directory.example.org/add-listing"
    assert body["steps"]

    listed = authenticated_client.get(f"{API}/websites", params={"search": "example.org"})
    row = listed.json()["items"][0]
    assert row["recipe"]["checked_at"]
    assert row["signup_url"] == "https://directory.example.org/signup"


def test_the_batch_probe_skips_websites_that_already_have_a_recipe(
    authenticated_client, site: dict[str, str]
) -> None:
    first = authenticated_client.post(
        f"{API}/websites",
        json={"opportunity_url": "https://directory.example.org/", "name": "One"},
    ).json()
    authenticated_client.post(
        f"{API}/websites",
        json={"opportunity_url": "https://other.example.org/join", "name": "Two"},
    )
    authenticated_client.post(f"{API}/websites/{first['id']}/recipe")

    body = authenticated_client.post(f"{API}/websites/recipes", json={"limit": 5}).json()
    assert body["probed"] == 1
    assert body["rows"][0]["domain"] == "other.example.org"
