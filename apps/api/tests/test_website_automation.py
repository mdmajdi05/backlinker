"""Tests of the guided per website automatic form setup.

The automatic adapters are only safe when the operator can say which form
control receives which value and how a successful submission is recognised.
These tests cover validation, the static field detector and the fact that the
per website configuration reaches the adapter (instead of a project wide one).
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from app.core.net import FetchResult
from app.db.models import AutomationAdapter, Opportunity, Task, Website
from app.services import automation_setup
from tests.conftest import API


def _website(client: TestClient) -> dict:
    response = client.post(
        f"{API}/websites",
        json={
            "opportunity_url": "https://directory.example.org/add-your-business",
            "name": "Example Directory",
            "category": "BUSINESS_DIRECTORY",
            "niche": "pets",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _form_html() -> str:
    return """
    <html><body>
      <form action="/submit" method="post">
        <label for="company">Company name</label>
        <input id="company" name="company" type="text">
        <label for="email">E-mail</label>
        <input id="email" name="email" type="email">
        <label for="mailing">Mailing address</label>
        <input id="mailing" name="mailing_address" type="text">
        <textarea name="description" placeholder="Description"></textarea>
        <input type="hidden" name="csrf" value="token">
        <input type="password" name="password">
        <input type="submit" value="Send">
      </form>
      <script src="https://www.google.com/recaptcha/api.js"></script>
    </body></html>
    """


def test_the_detector_proposes_selectors_and_flags_a_captcha(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    website = _website(authenticated_client)

    def fake_safe_get(url: str, **kwargs: Any) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content=_form_html(),
            headers={"content-type": "text/html"},
            elapsed_ms=5,
            redirects=[],
        )

    monkeypatch.setattr(automation_setup, "safe_get", fake_safe_get)
    response = authenticated_client.post(
        f"{API}/websites/{website['id']}/automation/detect", json={}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reachable"] is True
    assert body["form_found"] is True
    assert body["has_captcha"] is True
    assert body["has_password"] is True
    by_label = {field["label"]: field for field in body["fields"]}
    assert by_label["Company name"]["token"] == "name"
    assert by_label["E-mail"]["token"] == "email"
    assert by_label["Mailing address"]["token"] == "address"
    assert by_label["Description"]["token"] == "description"
    # Hidden, password and submit controls are not proposed.
    assert all("csrf" not in field["selector"] for field in body["fields"])


def test_a_complete_automation_config_is_stored_on_the_website(
    authenticated_client: TestClient, db_session
) -> None:
    website = _website(authenticated_client)
    response = authenticated_client.put(
        f"{API}/websites/{website['id']}/automation",
        json={
            "adapter": "playwright_form",
            "form_url": "https://directory.example.org/add-your-business",
            "fields": {
                "[name='company']": "{{name}}",
                "[name='email']": "{{email}}",
                "[name='description']": "{{description}}",
            },
            "success_kind": "text",
            "success_value": "Thank you for your submission",
            "submit_selector": "button[type='submit']",
            "timeout_ms": 45000,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["adapter_key"] == "playwright_form"
    assert body["adapter_config"]["form_url"].endswith("/add-your-business")
    assert body["adapter_config"]["success_kind"] == "text"
    assert body["adapter_config"]["success_value"] == "Thank you for your submission"

    db_session.rollback()
    row = db_session.get(Website, website["id"])
    assert row is not None
    adapter = db_session.get(AutomationAdapter, row.adapter_id)
    assert adapter is not None
    assert adapter.key == "playwright_form"
    assert row.adapter_config["success_text"] == "Thank you for your submission"
    assert row.adapter_config["fields"]["[name='company']"] == "{{name}}"


def test_an_incomplete_automation_config_is_rejected(authenticated_client: TestClient) -> None:
    website = _website(authenticated_client)
    response = authenticated_client.put(
        f"{API}/websites/{website['id']}/automation",
        json={
            "adapter": "playwright_form",
            "form_url": "https://directory.example.org/add-your-business",
            "fields": {"[name='company']": "{{name}}"},
            "success_kind": "text",
            "success_value": "",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_automation"

    response = authenticated_client.put(
        f"{API}/websites/{website['id']}/automation",
        json={
            "adapter": "playwright_form",
            "form_url": "https://directory.example.org/add-your-business",
            "fields": {},
            "success_kind": "text",
            "success_value": "Thank you",
        },
    )
    assert response.status_code == 422


def test_automation_can_be_cleared_again(authenticated_client: TestClient) -> None:
    website = _website(authenticated_client)
    saved = authenticated_client.put(
        f"{API}/websites/{website['id']}/automation",
        json={
            "adapter": "http_form",
            "form_url": "https://directory.example.org/add-your-business",
            "fields": {"[name='company']": "{{name}}"},
            "success_kind": "selector",
            "success_value": ".thank-you",
        },
    )
    assert saved.status_code == 200, saved.text

    cleared = authenticated_client.delete(f"{API}/websites/{website['id']}/automation")
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["adapter_id"] is None
    assert body["adapter_key"] is None
    assert body["adapter_config"] is None


def test_clearing_the_setup_restores_the_previous_method(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        f"{API}/websites",
        json={
            "opportunity_url": "https://directory.example.org/contact",
            "name": "Example Directory",
            "category": "BUSINESS_DIRECTORY",
            "submission_method": "EMAIL_OUTREACH",
        },
    )
    assert response.status_code == 201, response.text
    website = response.json()
    saved = authenticated_client.put(
        f"{API}/websites/{website['id']}/automation",
        json={
            "adapter": "playwright_form",
            "form_url": "https://directory.example.org/contact",
            "fields": {"[name='company']": "{{name}}"},
            "success_kind": "text",
            "success_value": "Thank you",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["submission_method"] == "BROWSER_FORM"

    cleared = authenticated_client.delete(f"{API}/websites/{website['id']}/automation")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["submission_method"] == "EMAIL_OUTREACH"


def test_the_website_config_reaches_the_adapter(
    authenticated_client: TestClient, db_session, project_id: str, opportunity_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project wide config must not overwrite the website specific one."""
    from app.services import submission as submission_service
    from app.services.adapters.base import RESULT_WAITING_USER, SubmissionResult

    db_session.rollback()
    opportunity = db_session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    website = db_session.get(Website, opportunity.website_id)
    assert website is not None
    adapter_row = (
        db_session.query(AutomationAdapter)
        .filter(AutomationAdapter.key == "playwright_form")
        .one()
    )
    website.adapter_id = adapter_row.id
    website.adapter_config = {
        "adapter": "playwright_form",
        "form_url": "https://directory.example.org/add-your-business",
        "fields": {"[name='company']": "{{name}}"},
        "success_text": "Thank you",
    }
    task = Task(
        project_id=project_id,
        opportunity_id=opportunity.id,
        website_id=website.id,
        type="SUBMIT",
        status="RUNNING",
        idempotency_key="SUBMIT:website-config",
    )
    db_session.add(task)
    db_session.commit()

    captured: dict[str, Any] = {}

    class CaptureAdapter:
        key = "playwright_form"
        name = "Capture adapter"
        kind = "BROWSER_AUTOMATION"
        description = ""
        supported_categories = ()
        supported_methods = ("BROWSER_FORM",)
        required_config: ClassVar[dict[str, str]] = {
            "form_url": "string",
            "fields": "object",
        }
        required_user_fields = ()
        registration_required = False
        manual_approval_required = False
        automatable = True
        verification_method = "http_link_check"
        retryable_errors = ()
        restrictions = ""
        success_signals = ()
        domains = ()

        def preflight(self, ctx):
            return None

        def submit(self, ctx):
            captured.update(ctx.adapter_config)
            return SubmissionResult(
                status=RESULT_WAITING_USER,
                message="Captured",
                requires_human=True,
                evidence={"submission_pack": {"instructions": ["captured"]}},
            )

    adapter = CaptureAdapter()
    monkeypatch.setattr(submission_service, "resolve_adapter", lambda db, identifier: adapter)
    outcome = submission_service.execute_submission(db_session, task)
    assert outcome.status == RESULT_WAITING_USER
    assert captured["form_url"] == "https://directory.example.org/add-your-business"
    assert captured["fields"] == {"[name='company']": "{{name}}"}
    assert captured["success_text"] == "Thank you"
