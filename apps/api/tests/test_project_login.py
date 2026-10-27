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
    def __init__(self, *pages: _FakePage, state: dict | None = None) -> None:
        self.pages = list(pages)
        self._state = state or {"cookies": [], "origins": []}

    def storage_state(self) -> dict:
        return self._state

    def cookies(self) -> list[dict]:
        return list(self._state.get("cookies") or [])


class _NullScope:
    def __enter__(self):
        return None

    def __exit__(self, *_exc) -> bool:
        return False


def _window(website_id: str = "website-1", mode: str = "site") -> login_browser.LoginWindow:
    return login_browser.LoginWindow(
        "project-1",
        "https://dir.example/add",
        mode=mode,
        website_id=website_id,
        email_hint=None,
    )


def test_a_google_cookie_from_another_domain_is_not_a_login() -> None:
    assert project_login.google_session_present(
        [{"name": "SID", "domain": ".google.com"}]
    )
    assert not project_login.google_session_present(
        [{"name": "SID", "domain": "google.com.evil.io"}]
    )
    assert not project_login.google_session_present(
        [{"name": "SID", "domain": "notgoogle.com"}]
    )


def test_a_stale_google_cookie_is_not_a_fresh_login(monkeypatch) -> None:
    """Re-opening the window of an expired project must not claim a login."""

    cookies = [{"name": "SID", "domain": ".google.com", "value": "old"}]
    window = _window(mode="google")
    window._prime_google_baseline(_FakeContext(state={"cookies": cookies}))

    statuses: list[str] = []
    resumed: list[int] = []
    monkeypatch.setattr(login_browser, "session_scope", _NullScope)
    monkeypatch.setattr(
        project_login, "save_storage_state", lambda *_a, **_k: statuses.append("save")
    )
    monkeypatch.setattr(
        project_login,
        "get_profile",
        lambda *_a, **_k: type("Row", (), {"storage_state_encrypted": "x"})(),
    )
    monkeypatch.setattr(
        project_login,
        "set_status",
        lambda _db, _pid, value, **_k: statuses.append(value),
    )
    monkeypatch.setattr(
        project_login,
        "resume_login_paused_tasks",
        lambda *_a, **_k: resumed.append(1) or 1,
    )

    window.explicit_finish = True
    window._save_google(_FakeContext(state={"cookies": cookies}), {"cookies": cookies})
    assert window.saved is False
    assert "save" not in statuses
    assert project_login.STATUS_EXPIRED in statuses
    assert resumed == []
    assert window.resumed == 0


def test_a_changed_google_cookie_is_a_real_login(monkeypatch) -> None:
    window = _window(mode="google")
    window._prime_google_baseline(
        _FakeContext(
            state={"cookies": [{"name": "SID", "domain": ".google.com", "value": "old"}]}
        )
    )

    saved: list[str] = []
    resumed: list[int] = []
    monkeypatch.setattr(login_browser, "session_scope", _NullScope)
    monkeypatch.setattr(
        project_login, "save_storage_state", lambda *_a, **_k: saved.append("save")
    )
    monkeypatch.setattr(
        project_login, "set_status", lambda *_a, **_k: saved.append("connected")
    )
    monkeypatch.setattr(
        login_browser.LoginWindow,
        "_detect_google_email",
        lambda *_a, **_k: "new@example.com",
    )
    monkeypatch.setattr(
        project_login,
        "resume_login_paused_tasks",
        lambda *_a, **_k: resumed.append(1) or 2,
    )

    cookies = [{"name": "SID", "domain": ".google.com", "value": "new"}]
    window._save_google(_FakeContext(state={"cookies": cookies}), {"cookies": cookies})

    assert window.saved is True
    assert saved == ["save", "connected"]
    assert resumed == [1]
    assert window.final_status == project_login.STATUS_CONNECTED


def test_a_public_page_is_not_a_website_login(monkeypatch) -> None:
    window = _window()
    page = _FakePage("https://dir.example/add-your-business")

    # Nothing was ever locked, so there is nothing to be connected to.
    window._inspect(_FakeContext(page), page)
    assert window._saw_wall is False

    saved: list[str] = []
    monkeypatch.setattr(login_browser, "session_scope", _NullScope)
    monkeypatch.setattr(
        project_login, "save_storage_state", lambda *_a, **_k: saved.append("save")
    )
    window.explicit_finish = True
    window._save_site(_FakeContext(page), {"cookies": []})
    assert window.saved is False
    assert saved == []


def test_a_login_wall_that_disappears_is_a_real_website_login(monkeypatch) -> None:
    window = _window()
    wall = _FakePage("https://dir.example/login")
    context = _FakeContext(wall)

    window._inspect(context, wall)
    assert window._saw_wall is True
    # Seeing the wall is not a login - the operator still has to finish.
    assert window._connected_once is False

    dashboard = _FakePage("https://dir.example/dashboard")
    context.pages.append(dashboard)

    marks: list[tuple] = []
    monkeypatch.setattr(login_browser, "session_scope", _NullScope)
    monkeypatch.setattr(project_login, "save_storage_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        project_login, "mark_site", lambda *_a, **_k: marks.append(_a)
    )
    monkeypatch.setattr(
        project_login, "resume_login_paused_tasks", lambda *_a, **_k: 1
    )

    window.explicit_finish = True
    window._save_site(context, {"cookies": [{"name": "sid", "domain": "dir.example"}]})

    assert window.saved is True
    assert marks
    assert marks[0][3] == project_login.SITE_CONNECTED


def test_finishing_a_site_window_without_a_session_does_not_claim_connected(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")

    monkeypatch.setattr(
        login_browser,
        "finish",
        lambda _project_id, **_kwargs: {
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


def test_a_site_wall_does_not_expire_the_google_login(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")

    project_login.pause_for_login(
        db_session,
        project["id"],
        added["website_id"],
        "This website asks for a login.",
        google=False,
    )

    # A directory that wants its own account is not a Google problem.
    assert (
        project_login.describe(db_session, project["id"])["status"]
        == project_login.STATUS_NOT_CONNECTED
    )
    site = project_login.describe_site(
        db_session, project["id"], added["website_id"]
    )
    assert site["status"] == project_login.SITE_LOGIN_REQUIRED


def test_resume_after_a_site_login_only_requeues_that_website(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    first = _add_website(authenticated_client, project["id"], "https://one.example/add")
    second = _add_website(authenticated_client, project["id"], "https://two.example/add")
    tasks = []
    for index, website in enumerate((first, second)):
        task, _created = queue_service.enqueue(
            db_session,
            task_type="SUBMIT",
            project_id=project["id"],
            website_id=website["website_id"],
            idempotency_key=f"site-login-{index}",
        )
        task.status = "WAITING_FOR_USER"
        task.last_error = f"{project_login.LOGIN_REQUIRED_PREFIX} login"
        tasks.append(task)
    db_session.commit()

    resumed = project_login.resume_login_paused_tasks(
        db_session, project["id"], website_id=first["website_id"]
    )

    assert resumed == 1
    db_session.refresh(tasks[0])
    db_session.refresh(tasks[1])
    assert tasks[0].status == "QUEUED"
    assert tasks[1].status == "WAITING_FOR_USER"


def test_a_closed_window_is_not_reported_as_open(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    row = project_login.get_profile(db_session, project["id"], create=True)
    assert row is not None
    row.status = project_login.STATUS_LOGIN_OPEN
    row.storage_state_encrypted = "encrypted"
    db_session.commit()

    described = project_login.describe(db_session, project["id"])

    assert described["login_open"] is False
    assert described["status"] == project_login.STATUS_CONNECTED


def test_purging_a_project_removes_its_browser_profile(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    row = project_login.get_profile(db_session, project["id"], create=True)
    assert row is not None
    directory = project_login.profile_dir(project["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Cookies").write_text("cookie", encoding="utf-8")
    row.profile_dir = str(directory)
    db_session.commit()

    assert (
        authenticated_client.delete(f"{API}/projects/{project['id']}").status_code
        == 204
    )
    response = authenticated_client.delete(f"{API}/recycle-bin/project/{project['id']}")

    assert response.status_code in (200, 204), response.text
    assert not directory.exists()


def test_the_form_finder_never_reports_a_login_form(
    authenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")

    def fake_safe_get(url: str, **kwargs: Any) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content="<html><body>Nothing to submit here.</body></html>",
            headers={"content-type": "text/html"},
            elapsed_ms=3,
            redirects=[],
        )

    def fake_inspect(url: str) -> dict[str, Any]:
        return {
            "form_url": url,
            "final_url": "https://dir.example/login",
            "reachable": True,
            "http_status": 200,
            "form_found": True,
            "fields": [
                {"label": "Email", "selector": "#email", "type": "email"},
                {"label": "Password", "selector": "#password", "type": "password"},
            ],
            "has_captcha": False,
            "has_password": True,
            "message": "2 fields were found.",
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


def test_a_stale_session_write_is_rejected(authenticated_client, db_session) -> None:
    project = _project(authenticated_client)
    project_login.save_storage_state(db_session, project["id"], {"cookies": []})
    stale_version = project_login.profile_version(db_session, project["id"])
    project_login.save_storage_state(
        db_session, project["id"], {"cookies": [{"name": "new"}]}
    )

    with pytest.raises(project_login.LoginStateConflict):
        project_login.save_storage_state(
            db_session,
            project["id"],
            {"cookies": [{"name": "old"}]},
            expected_version=stale_version,
        )


def test_a_decryption_error_is_not_replaced_by_a_login_wall(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    row = project_login.get_profile(db_session, project["id"], create=True)
    assert row is not None
    row.status = project_login.STATUS_ERROR
    row.last_error = "The stored browser session could not be decrypted."
    db_session.commit()

    project_login.pause_for_login(
        db_session, project["id"], None, "This site asks for a login.", google=True
    )

    described = project_login.describe(db_session, project["id"])
    assert described["status"] == project_login.STATUS_ERROR
    assert "decrypted" in (described["last_error"] or "")
