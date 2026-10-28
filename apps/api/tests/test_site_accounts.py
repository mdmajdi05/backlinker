"""The per project / per website account pipeline.

The suite covers the parts that must never be wrong even when no browser is
available:

* the one-time code is bound to the address alias of its own row and a code
  can never be claimed twice,
* a generated password only decrypts with the associated data of its row,
* the batch refuses to run while the login window is open,
* the backlink page scoring rejects login walls,
* the CSV report really carries the generated username and password.
"""

from __future__ import annotations

import email
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.db.models import Opportunity, Project, SiteAccount, Website
from app.services import backlink_target, gmail_otp, site_accounts

API = "/api/v1"


def _project(db, slug: str = "acme") -> Project:
    project = Project(
        name="Acme", slug=slug, target_website="https://acme.example"
    )
    db.add(project)
    db.commit()
    return project


def _website(db, domain: str = "directory.example.org") -> Website:
    website = Website(
        name="Directory",
        domain=domain,
        opportunity_url=f"https://{domain}/add",
        category="BUSINESS_DIRECTORY",
    )
    db.add(website)
    db.commit()
    return website


# ---------------------------------------------------------------------------
# One-time codes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Your verification code is 483920.", "483920"),
        ("Use 123456 to confirm your email address.", "123456"),
        ("Security code: 90211", "90211"),
        ("Hello, your order 12345678 shipped", None),
        ("Thanks for signing up in 2026", None),
        ("", None),
    ],
)
def test_extract_code(text: str, expected: str | None) -> None:
    assert gmail_otp.extract_code(text) == expected


def test_alias_is_unique_per_row() -> None:
    first = gmail_otp.alias_for("inbox@gmail.com", gmail_otp.alias_token("p1", "w1"))
    second = gmail_otp.alias_for("inbox@gmail.com", gmail_otp.alias_token("p1", "w2"))
    assert first.startswith("inbox+")
    assert first.endswith("@gmail.com")
    assert first != second
    # Dot aliases are the fallback for sites that refuse "+".
    dot_alias = gmail_otp.dot_alias_for("inbox@gmail.com", "tok")
    assert "." in dot_alias.split("@")[0]


def _raw_message(
    *,
    to: str,
    subject: str,
    body: str,
    sender: str = "no-reply@directory.example.org",
    message_id: str = "<one@example.org>",
    minutes_ago: int = 1,
) -> bytes:
    message = email.message.EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message["Date"] = (
        datetime.now(UTC) - timedelta(minutes=minutes_ago)
    ).strftime("%a, %d %b %Y %H:%M:%S %z")
    message.set_content(body)
    return message.as_bytes()


def _message(**kwargs: object) -> gmail_otp._Message:
    parsed = gmail_otp._message_from_uid("1", _raw_message(**kwargs))  # type: ignore[arg-type]
    assert parsed is not None
    return parsed


def test_claim_uses_only_the_own_alias() -> None:
    credentials = gmail_otp.GmailSettings(address="inbox@gmail.com", app_password="x" * 16)
    inbox = gmail_otp.OtpInbox(credentials)
    own = _message(
        to="inbox+rowone@gmail.com",
        subject="Your code",
        body="Your verification code is 111222.",
        message_id="<own@example.org>",
    )
    foreign = _message(
        to="inbox+rowtwo@gmail.com",
        subject="Your code",
        body="Your verification code is 999888.",
        message_id="<foreign@example.org>",
    )
    code, reason = inbox.claim(
        [own, foreign],
        alias="inbox+rowone@gmail.com",
        base_address="inbox@gmail.com",
        site_domain="directory.example.org",
    )
    assert reason is None
    assert code is not None
    assert code.code == "111222"

    # The code of the other row is still free - it was not consumed.
    others = inbox.claim(
        [own, foreign],
        alias="inbox+rowtwo@gmail.com",
        base_address="inbox@gmail.com",
        site_domain="directory.example.org",
    )
    assert others[0] is not None
    assert others[0].code == "999888"


def test_claim_is_single_use() -> None:
    credentials = gmail_otp.GmailSettings(address="inbox@gmail.com", app_password="x" * 16)
    inbox = gmail_otp.OtpInbox(credentials)
    message = _message(
        to="inbox+row@gmail.com",
        subject="Your code",
        body="Your verification code is 424242.",
        message_id="<once@example.org>",
    )
    first, _ = inbox.claim(
        [message],
        alias="inbox+row@gmail.com",
        base_address="inbox@gmail.com",
        site_domain="directory.example.org",
    )
    second, _ = inbox.claim(
        [message],
        alias="inbox+row@gmail.com",
        base_address="inbox@gmail.com",
        site_domain="directory.example.org",
    )
    assert first is not None
    assert second is None


def test_two_different_codes_for_one_alias_are_refused() -> None:
    credentials = gmail_otp.GmailSettings(address="inbox@gmail.com", app_password="x" * 16)
    inbox = gmail_otp.OtpInbox(credentials)
    first = _message(
        to="inbox+row@gmail.com",
        subject="Your code",
        body="Your verification code is 111111.",
        message_id="<a@example.org>",
        minutes_ago=2,
    )
    second = _message(
        to="inbox+row@gmail.com",
        subject="Your code",
        body="Your verification code is 222222.",
        message_id="<b@example.org>",
        minutes_ago=1,
    )
    code, reason = inbox.claim(
        [first, second],
        alias="inbox+row@gmail.com",
        base_address="inbox@gmail.com",
        site_domain="directory.example.org",
    )
    assert code is None
    assert reason is not None
    assert "by hand" in reason


def test_without_alias_only_the_sending_site_is_accepted() -> None:
    credentials = gmail_otp.GmailSettings(address="inbox@gmail.com", app_password="x" * 16)
    inbox = gmail_otp.OtpInbox(credentials)
    unrelated = _message(
        to="inbox@gmail.com",
        subject="Your code",
        body="Your verification code is 555555.",
        sender="no-reply@unrelated.example",
        message_id="<unrelated@example.org>",
    )
    code, _ = inbox.claim(
        [unrelated],
        alias="",
        base_address="inbox@gmail.com",
        site_domain="directory.example.org",
    )
    assert code is None


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def test_password_is_bound_to_its_row(db_session) -> None:
    project = _project(db_session)
    website = _website(db_session)
    row = SiteAccount(project_id=project.id, website_id=website.id)
    db_session.add(row)
    db_session.commit()

    site_accounts.set_password(row, "S3cret-Value-1")
    db_session.commit()
    assert site_accounts.password_of(row) == "S3cret-Value-1"

    # The stored ciphertext is useless under the associated data of another row.
    with pytest.raises(ValueError, match="integrity"):
        decrypt(
            row.password_encrypted or "",
            settings.secret_key,
            site_accounts._aad(project.id, "another-website"),
        )


def test_generated_credentials_are_strong() -> None:
    password = site_accounts.generate_password()
    assert len(password) >= 16
    assert any(char.islower() for char in password)
    assert any(char.isupper() for char in password)
    assert any(char.isdigit() for char in password)
    assert any(char in "!@#$%&*?" for char in password)


def test_account_payload_hides_the_password_when_asked(db_session) -> None:
    project = _project(db_session)
    website = _website(db_session)
    row = SiteAccount(project_id=project.id, website_id=website.id, username="acmeuser")
    site_accounts.set_password(row, "Pass-1234-Value")
    db_session.add(row)
    db_session.commit()

    assert site_accounts.account_payload(db_session, row)["password"] == "Pass-1234-Value"
    hidden = site_accounts.account_payload(db_session, row, reveal=False)
    assert hidden["password"] is None
    assert hidden["has_password"] is True


# ---------------------------------------------------------------------------
# Batch guards
# ---------------------------------------------------------------------------
def test_batch_refuses_an_open_login_window(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(db_session)
    monkeypatch.setattr(
        "app.services.login_browser.is_open", lambda project_id: True
    )
    with pytest.raises(RuntimeError, match="login window"):
        site_accounts.start_batch(db_session, project)


def test_batch_refuses_when_automation_is_off(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(db_session)
    monkeypatch.setattr(settings, "allow_browser_automation", False)
    with pytest.raises(RuntimeError, match="turned off"):
        site_accounts.start_batch(db_session, project)


def test_stopping_an_idle_batch_is_a_no_op() -> None:
    assert site_accounts.stop_batch("no-such-project") is False
    assert site_accounts.batch_state("no-such-project")["running"] is False


# ---------------------------------------------------------------------------
# Backlink page scoring
# ---------------------------------------------------------------------------
def test_score_prefers_a_real_link_form() -> None:
    score, reasons = backlink_target.score_page(
        url="https://directory.example.org/submit",
        title="Submit your website",
        link_text="Add your business",
        fields=[
            {"name": "website", "label": "Your website"},
            {"name": "description", "label": "Description"},
        ],
        has_submit=True,
        body_text="Add your website to our directory.",
    )
    assert score >= backlink_target.FOUND_AT
    assert any("URL" in reason for reason in reasons)


def test_score_rejects_a_login_wall() -> None:
    score, _ = backlink_target.score_page(
        url="https://directory.example.org/login",
        title="Sign in",
        link_text="",
        fields=[{"name": "password", "label": "Password"}],
        has_submit=True,
        body_text="Sign in to continue",
    )
    assert score < backlink_target.FOUND_AT


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_accounts_need_a_login(client: TestClient) -> None:
    assert client.get(f"{API}/projects/unknown/accounts").status_code == 401


def test_accounts_are_private_to_the_owner(
    authenticated_client: TestClient, project_id: str, other_auth_headers: dict[str, str]
) -> None:
    response = authenticated_client.get(
        f"{API}/projects/{project_id}/accounts", headers=other_auth_headers
    )
    assert response.status_code == 403


def test_read_accounts_payload(authenticated_client: TestClient, project_id: str) -> None:
    response = authenticated_client.get(f"{API}/projects/{project_id}/accounts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == project_id
    assert body["accounts"] == {}
    assert body["batch"]["running"] is False
    assert body["gmail"]["configured"] is False


def test_provision_is_rejected_while_automation_is_off(
    authenticated_client: TestClient,
    project_id: str,
    opportunity_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "allow_browser_automation", False)
    response = authenticated_client.post(
        f"{API}/projects/{project_id}/accounts/provision", json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cannot_start"


def test_gmail_settings_validation(authenticated_client: TestClient) -> None:
    bad_address = authenticated_client.put(
        f"{API}/accounts/gmail",
        json={"address": "not-an-address", "app_password": "a" * 16},
    )
    assert bad_address.status_code == 400
    short = authenticated_client.put(
        f"{API}/accounts/gmail",
        json={"address": "inbox@gmail.com", "app_password": "short"},
    )
    assert short.status_code == 400


def test_gmail_settings_roundtrip(db_session) -> None:
    stored = gmail_otp.save_settings(
        db_session, address="inbox@gmail.com", app_password="abcdefghijklmnop"
    )
    assert stored.address == "inbox@gmail.com"
    assert gmail_otp.read_settings(db_session) is not None
    payload = gmail_otp.status_payload(gmail_otp.read_settings(db_session))
    assert payload["configured"] is True
    assert payload["address"] == "inbox@gmail.com"
    gmail_otp.delete_settings(db_session)
    assert gmail_otp.read_settings(db_session) is None


def test_campaign_row_carries_the_account_of_its_website(
    authenticated_client: TestClient, project_id: str, opportunity_id: str, db_session
) -> None:
    db_session.rollback()
    opportunity = db_session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    row = SiteAccount(
        project_id=project_id,
        website_id=opportunity.website_id,
        strategy=site_accounts.STRATEGY_SIGNUP,
        status=site_accounts.STATUS_ACTIVE,
        username="acmeuser1",
        email="inbox+abc@gmail.com",
        backlink_url="https://site.example/profile",
        backlink_confidence=88,
    )
    site_accounts.set_password(row, "Pass-1234-Value")
    db_session.add(row)
    db_session.commit()

    body = authenticated_client.get(f"{API}/projects/{project_id}/campaign").json()
    matching = [item for item in body["rows"] if item["website_id"] == row.website_id]
    assert matching, body
    account = matching[0]["account"]
    assert account["username"] == "acmeuser1"
    assert account["password"] == "Pass-1234-Value"
    assert account["backlink_url"] == "https://site.example/profile"
    assert body["summary"]["account_active"] == 1

    report = authenticated_client.get(f"{API}/projects/{project_id}/campaign/report.csv")
    assert report.status_code == 200
    text = report.text
    header = text.splitlines()[0]
    for column in ("Username", "Password", "Backlink page", "Account strategy"):
        assert column in header
    assert "acmeuser1" in text
    assert "Pass-1234-Value" in text


def test_website_is_untouched_when_no_account_exists(
    authenticated_client: TestClient, project_id: str, opportunity_id: str, db_session
) -> None:
    db_session.rollback()
    body = authenticated_client.get(f"{API}/projects/{project_id}/campaign").json()
    assert body["summary"]["account_missing"] == 1
    assert body["rows"][0]["account"] is None


def test_account_row_is_unique_per_project_and_website(db_session) -> None:
    project = _project(db_session)
    website = _website(db_session)
    first = site_accounts.ensure_account(db_session, project.id, website.id)
    second = site_accounts.ensure_account(db_session, project.id, website.id)
    assert first.id == second.id


def test_counts_for_project(db_session) -> None:
    project = _project(db_session)
    first = _website(db_session, "one.example.org")
    second = _website(db_session, "two.example.org")
    db_session.add(
        SiteAccount(
            project_id=project.id, website_id=first.id, status=site_accounts.STATUS_ACTIVE
        )
    )
    db_session.add(
        SiteAccount(
            project_id=project.id,
            website_id=second.id,
            status=site_accounts.STATUS_NEEDS_HUMAN,
        )
    )
    db_session.commit()
    counts = site_accounts.counts_for_project(db_session, project.id)
    assert counts[site_accounts.STATUS_ACTIVE] == 1
    assert counts[site_accounts.STATUS_NEEDS_HUMAN] == 1


def test_website_model_is_reachable(db_session) -> None:
    """A guard against a typo in the column the batch reads."""
    website = _website(db_session)
    assert website.opportunity_url.endswith("/add")


def test_encrypt_roundtrip_uses_the_installation_secret() -> None:
    value = encrypt("hello", settings.secret_key, "aad")
    assert decrypt(value, settings.secret_key, "aad") == "hello"
