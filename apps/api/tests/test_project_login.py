"""The per project Google login and the automatic form finder.

The product promise is narrow and testable:

* a project owns one isolated browser profile and one encrypted session,
* a site that answers with a login wall pauses the task instead of failing it,
* the project clearly reports ``expired`` / ``login required``,
* a fresh login queues the paused tasks again,
* the form finder follows the "add listing" links but never claims a form it
  did not see.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.net import FetchResult
from app.db.models import Task
from app.services import form_finder, login_browser, project_login
from app.services import queue as queue_service
from tests.conftest import API


def _project(client: TestClient) -> dict:
    response = client.post(
        f"{API}/projects",
        json={"name": "Login project", "target_website": "https://acme.example"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_website(client: TestClient, project_id: str, url: str) -> dict:
    response = client.post(
        f"{API}/projects/{project_id}/campaign/websites", json={"text": url}
    )
    assert response.status_code == 200, response.text
    return response.json()["results"][0]


def test_a_new_project_starts_without_a_google_login(authenticated_client) -> None:
    project = _project(authenticated_client)

    response = authenticated_client.get(f"{API}/projects/{project['id']}/login")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "NOT_CONNECTED"
    assert body["email"] is None
    assert body["paused_tasks"] == 0
    assert body["sites"] == []

    # The project detail exposes the same state, so the card can render it
    # without a second request.
    detail = authenticated_client.get(f"{API}/projects/{project['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["login"]["status"] == "NOT_CONNECTED"


def test_the_stored_session_is_encrypted_and_round_trips(
    authenticated_client, db_session, project_id: str
) -> None:
    state = {
        "cookies": [
            {"name": "SID", "value": "secret-value", "domain": ".google.com", "path": "/"}
        ],
        "origins": [],
    }

    project_login.save_storage_state(db_session, project_id, state)
    db_session.commit()

    row = project_login.get_profile(db_session, project_id)
    assert row is not None
    assert row.storage_state_encrypted
    assert "secret-value" not in row.storage_state_encrypted

    loaded = project_login.load_storage_state(db_session, project_id)
    assert loaded == state

    # A different project cannot decrypt the stored state of this one.
    other = _project(authenticated_client)
    assert project_login.load_storage_state(db_session, other["id"]) is None


def test_a_login_wall_pauses_the_task_and_a_login_resumes_it(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")

    # The project already had a session: the wall means "expired", not "never
    # connected".
    project_login.save_storage_state(
        db_session,
        project["id"],
        {"cookies": [{"name": "SID", "value": "x", "domain": ".google.com", "path": "/"}]},
    )

    task, _created = queue_service.enqueue(
        db_session,
        task_type="SUBMIT",
        project_id=project["id"],
        opportunity_id=added["opportunity_id"],
        website_id=added["website_id"],
        idempotency_key="login-wall",
    )
    task.status = "WAITING_FOR_USER"
    task.requires_human = True
    task.last_error = f"{project_login.LOGIN_REQUIRED_PREFIX} This site asks for a login."
    db_session.commit()

    project_login.pause_for_login(
        db_session,
        project["id"],
        added["website_id"],
        "This site asks for a login.",
    )

    login = project_login.describe(db_session, project["id"])
    assert login["status"] == "EXPIRED"
    assert login["paused_tasks"] == 1

    site = project_login.describe_site(db_session, project["id"], added["website_id"])
    assert site["status"] == "EXPIRED"

    # The campaign shows the row as "login needed" instead of a failure.
    campaign = authenticated_client.get(f"{API}/projects/{project['id']}/campaign")
    assert campaign.status_code == 200, campaign.text
    row = campaign.json()["rows"][0]
    assert row["status"] == "LOGIN_NEEDED"
    assert campaign.json()["summary"]["login_needed"] == 1

    # A fresh login queues the paused task again.
    resumed = project_login.resume_login_paused_tasks(db_session, project["id"])
    db_session.commit()
    assert resumed == 1
    db_session.refresh(task)
    assert task.status == "QUEUED"
    assert project_login.count_login_paused(db_session, project["id"]) == 0


def test_a_wall_without_a_session_is_reported_as_login_required(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")

    project_login.pause_for_login(
        db_session, project["id"], added["website_id"], "This site asks for a login."
    )

    login = project_login.describe(db_session, project["id"])
    assert login["status"] == "NOT_CONNECTED"
    site = project_login.describe_site(db_session, project["id"], added["website_id"])
    assert site["status"] == "LOGIN_REQUIRED"


def test_a_google_session_is_recognised_from_its_cookies() -> None:
    assert project_login.google_session_present(
        [{"name": "SID", "domain": ".google.com"}]
    )
    assert not project_login.google_session_present(
        [{"name": "session", "domain": "directory.example"}]
    )


def test_the_form_finder_follows_an_add_listing_link(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/")

    homepage = """
    <html><body>
      <a href="/about">About</a>
      <a href="/add-your-business">Add your business</a>
      <a href="/login">Login</a>
    </body></html>
    """
    form_page = {
        "form_url": "https://dir.example/add-your-business",
        "final_url": "https://dir.example/add-your-business",
        "reachable": True,
        "http_status": 200,
        "form_found": True,
        "fields": [
            {
                "selector": "#company",
                "label": "Company",
                "token": "company_name",
                "kind": "text",
                "input_type": "text",
            }
        ],
        "has_captcha": False,
        "has_password": False,
        "message": "1 field was found.",
    }

    calls: list[str] = []

    def fake_safe_get(url: str, **kwargs: Any) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content=homepage,
            headers={"content-type": "text/html"},
            elapsed_ms=3,
            redirects=[],
        )

    def fake_inspect(url: str) -> dict[str, Any]:
        calls.append(url)
        if url.endswith("/add-your-business"):
            return form_page
        return {**form_page, "form_url": url, "fields": [], "form_found": False}

    monkeypatch.setattr(form_finder, "safe_get", fake_safe_get)
    monkeypatch.setattr(form_finder, "inspect_form_url", fake_inspect)

    response = authenticated_client.post(
        f"{API}/websites/{added['website_id']}/automation/find-form", json={}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["found"] is True
    assert body["form_url"] == "https://dir.example/add-your-business"
    assert body["fields"][0]["selector"] == "#company"
    assert any(call.endswith("/add-your-business") for call in calls)
    assert not any("/login" in call for call in calls)

    # Nothing was saved by the finder - the operator still has to review it.
    listing = authenticated_client.get(f"{API}/websites", params={"page_size": 50})
    assert listing.status_code == 200, listing.text
    stored = next(
        row for row in listing.json()["items"] if row["id"] == added["website_id"]
    )
    assert stored["adapter_config"] is None


def test_the_form_finder_does_not_invent_a_form(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/")

    def fake_safe_get(url: str, **kwargs: Any) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content="<html><body><a href='/add-listing'>Add a listing</a></body></html>",
            headers={"content-type": "text/html"},
            elapsed_ms=3,
            redirects=[],
        )

    def fake_inspect(url: str) -> dict[str, Any]:
        return {
            "form_url": url,
            "final_url": url,
            "reachable": True,
            "http_status": 200,
            "form_found": False,
            "fields": [],
            "has_captcha": False,
            "has_password": False,
            "message": "No form controls.",
        }

    monkeypatch.setattr(form_finder, "safe_get", fake_safe_get)
    monkeypatch.setattr(form_finder, "inspect_form_url", fake_inspect)

    response = authenticated_client.post(
        f"{API}/websites/{added['website_id']}/automation/find-form", json={}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["found"] is False
    assert body["form_url"] == ""
    assert body["message"]


def test_login_paused_tasks_belong_to_their_own_project(
    authenticated_client, db_session
) -> None:
    first = _project(authenticated_client)
    second = _project(authenticated_client)

    task, _created = queue_service.enqueue(
        db_session,
        task_type="SUBMIT",
        project_id=first["id"],
        idempotency_key="first-project-login",
    )
    task.status = "WAITING_FOR_USER"
    task.last_error = f"{project_login.LOGIN_REQUIRED_PREFIX} login"
    db_session.commit()

    assert project_login.count_login_paused(db_session, first["id"]) == 1
    assert project_login.count_login_paused(db_session, second["id"]) == 0

    resumed = project_login.resume_login_paused_tasks(db_session, second["id"])
    assert resumed == 0
    db_session.refresh(task)
    assert task.status == "WAITING_FOR_USER"
    assert isinstance(db_session.get(Task, task.id), Task)


class _FakeLocator:
    def count(self) -> int:
        return 0


class _FakePage:
    """The minimum of a Playwright page that the login detection touches."""

    def __init__(self, url: str, body: str = "") -> None:
        self.url = url
        self._body = body

    def is_closed(self) -> bool:
        return False

    def evaluate(self, _script: str) -> str:
        return self._body

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator()


class _FakeContext:
    def __init__(self, *pages: _FakePage) -> None:
        self.pages = list(pages)


def _window(website_id: str = "website-1") -> login_browser.LoginWindow:
    return login_browser.LoginWindow(
        "project-1",
        "https://dir.example/add",
        mode="site",
        website_id=website_id,
        email_hint=None,
    )


def test_a_public_page_is_not_a_website_login() -> None:
    window = _window()
    page = _FakePage("https://dir.example/add-your-business")

    # Nothing was ever locked, so there is nothing to be connected to.
    assert (
        window._site_is_open(
            _FakeContext(page), page, [{"name": "session", "domain": "dir.example"}]
        )
        is False
    )


def test_a_login_wall_that_disappears_is_a_real_website_login() -> None:
    window = _window()
    wall = _FakePage("https://dir.example/login")
    context = _FakeContext(wall)

    assert window._site_is_open(context, wall, [{"name": "SID"}]) is False
    assert window._saw_wall is True

    dashboard = _FakePage("https://dir.example/dashboard")
    context.pages.append(dashboard)
    assert window._site_is_open(context, dashboard, [{"name": "SID"}]) is True


def test_finishing_a_site_window_without_a_session_does_not_claim_connected(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")

    monkeypatch.setattr(
        login_browser,
        "finish",
        lambda _project_id: {
            "running": False,
            "saved": False,
            "resumed": 0,
            "message": "No website session was detected.",
        },
    )

    response = authenticated_client.post(
        f"{API}/projects/{project['id']}/login/sites/{added['website_id']}/finish"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is False
    assert body["site"]["status"] != project_login.SITE_CONNECTED
