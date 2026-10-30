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
from app.services import backlink_post, backlink_target, gmail_otp, site_accounts

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
        # A six digit order number is not a code when no mail talks about one.
        ("Your order 123456 shipped today", None),
        ("Thanks for signing up in 2026", None),
        ("Your verification code: A1B2C3", "A1B2C3"),
        ("Confirm your email with 77K9PQ", "77K9PQ"),
        # A number inside a URL is a token, never the code to type.
        ("Open https://example.org/c/123456 - your code is 654321", "654321"),
        ("OTP 1234 expires in 10 minutes", "1234"),
        ("", None),
    ],
)
def test_extract_code(text: str, expected: str | None) -> None:
    assert gmail_otp.extract_code(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Confirm your account: https://example.org/confirm?token=abc123",
            "https://example.org/confirm?token=abc123",
        ),
        (
            "Click https://example.org/about or verify at https://example.org/verify/xy",
            "https://example.org/verify/xy",
        ),
        ("Nothing here: https://example.org/about", None),
        ("", None),
    ],
)
def test_extract_link(text: str, expected: str | None) -> None:
    assert gmail_otp.extract_link(text) == expected


def test_extract_link_never_returns_an_unsubscribe_link() -> None:
    text = (
        "Confirm your account https://example.org/confirm?t=1 "
        "Unsubscribe https://example.org/unsubscribe?u=2"
    )
    assert gmail_otp.extract_link(text) == "https://example.org/confirm?t=1"
    assert gmail_otp.extract_link(
        "Only https://example.org/unsubscribe?u=2 here"
    ) is None


def test_extract_link_prefers_the_website_domain() -> None:
    text = (
        "Open https://tracker.example.net/confirm/abc or "
        "https://directory.example.org/verify/abc"
    )
    assert (
        gmail_otp.extract_link(text, "directory.example.org")
        == "https://directory.example.org/verify/abc"
    )


def test_field_role_recognises_the_common_signup_fields() -> None:
    role = site_accounts._field_role
    assert role({"type": "email"}) == "email"
    assert role({"type": "text", "name": "user_name"}) == "username"
    assert role({"type": "password", "name": "password"}) == "password"
    assert role({"type": "password", "name": "confirm_password"}) == "confirm"
    assert role({"type": "text", "placeholder": "First name"}) == "first"
    assert role({"type": "text", "placeholder": "Last name"}) == "last"
    assert role({"type": "text", "name": "company_name"}) == "company"
    assert role({"type": "tel"}) == "phone"
    assert role({"type": "url"}) == "website"
    assert role({"type": "text", "name": "country"}) == "country"
    assert role({"type": "text", "name": "postal_code"}) == "zip"
    assert role({"type": "text", "name": "favourite_colour"}) == ""


def test_browser_inbox_search_is_scoped_to_the_alias() -> None:
    inbox = gmail_otp.BrowserInbox(None, "owner@gmail.com")
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    url = inbox._search_url("owner+abc123@gmail.com", since)
    assert url.startswith("https://mail.google.com/mail/u/0/#search/")
    assert "owner%2Babc123%40gmail.com" in url
    assert "newer_than%3A1d" in url


def test_browser_inbox_without_an_alias_pauses_at_once() -> None:
    inbox = gmail_otp.BrowserInbox(None, "")
    code, reason = inbox.wait_for_code(
        alias="",
        since=datetime.now(UTC).replace(tzinfo=None),
        site_domain="example.com",
        timeout=1,
    )
    assert code is None
    assert reason


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
# Sign-up details (one username / password / e-mail for the project)
# ---------------------------------------------------------------------------
def test_signup_details_roundtrip_and_clear(db_session) -> None:
    project = _project(db_session)

    saved = site_accounts.save_signup_details(
        db_session,
        project,
        username="acme_team",
        password="Chosen-Pass-123",
        email="owner@gmail.com",
    )
    assert saved["username"] == "acme_team"
    assert saved["email"] == "owner@gmail.com"
    assert saved["password"] == "Chosen-Pass-123"
    assert saved["has_password"] is True

    # The ciphertext is bound to the project and never stores the plain text.
    row = db_session.get(Project, project.id)
    assert row is not None

    settings_row = site_accounts._settings_row(db_session, project.id)
    assert settings_row is not None
    assert "Chosen-Pass-123" not in str(settings_row.signup_details)

    hidden = site_accounts.signup_details(db_session, project.id, reveal=False)
    assert hidden["password"] is None
    assert hidden["has_password"] is True

    # An empty string clears a field: that value is generated per website.
    cleared = site_accounts.save_signup_details(
        db_session, row, username="", password="", email=""
    )
    assert cleared == {
        "username": "",
        "email": "",
        "password": None,
        "has_password": False,
        "captcha_wait": True,
    }


def test_signup_details_are_applied_to_a_row(db_session) -> None:
    project = _project(db_session)
    website = _website(db_session)
    details = {
        "username": "acme_team",
        "email": "owner@gmail.com",
        "password": "Chosen-Pass-123",
    }
    row = site_accounts.ensure_account(db_session, project.id, website.id)
    site_accounts.apply_signup_details(row, details)
    db_session.commit()

    assert row.username == "acme_team"
    assert site_accounts.password_of(row) == "Chosen-Pass-123"


def test_read_accounts_carries_the_signup_details(
    authenticated_client: TestClient, db_session, project_id: str
) -> None:
    project = db_session.get(Project, project_id)
    assert project is not None
    site_accounts.save_signup_details(
        db_session,
        project,
        username="acme_team",
        password="Chosen-Pass-123",
        email="owner@gmail.com",
    )

    body = authenticated_client.get(f"{API}/projects/{project_id}/accounts").json()
    assert body["details"]["username"] == "acme_team"
    assert body["details"]["email"] == "owner@gmail.com"
    assert body["details"]["password"] == "Chosen-Pass-123"
    assert body["google_connected"] is False
    assert body["google_email"] is None


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
        backlink_status="POSTED",
        backlink_published_url="https://site.example/profile/acmeuser1",
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
    assert account["backlink_status"] == "POSTED"
    assert (
        account["backlink_published_url"] == "https://site.example/profile/acmeuser1"
    )
    assert body["summary"]["account_active"] == 1

    report = authenticated_client.get(f"{API}/projects/{project_id}/campaign/report.csv")
    assert report.status_code == 200
    text = report.text
    header = text.splitlines()[0]
    for column in (
        "Username",
        "Password",
        "Backlink page",
        "Account strategy",
        "Published page",
        "Verification",
        "Posted link",
        "Backlink status",
    ):
        assert column in header
    assert "acmeuser1" in text
    assert "Pass-1234-Value" in text
    assert "https://site.example/profile/acmeuser1" in text


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


def test_submission_fields_are_classified_from_any_hint() -> None:
    role = backlink_post.field_role
    assert role({"label": "Your website", "type": "text"}) == "link"
    assert role({"name": "link_url", "type": "url"}) == "link"
    assert role({"label": "Website name"}) == "name"
    assert role({"label": "Anchor text"}) == "anchor"
    assert role({"label": "Description", "tag": "textarea"}) == "description"
    assert role({"label": "Business name"}) == "name"
    assert role({"label": "Phone", "type": "tel"}) == "phone"
    assert role({"label": "Category"}) == "category"
    assert role({"label": "Country"}) == "country"
    assert role({"label": "I agree to the terms", "type": "checkbox"}) == "terms"
    assert role({"label": "Favourite colour"}) == ""


def test_submission_values_come_from_the_business_profile() -> None:
    from types import SimpleNamespace

    profile = SimpleNamespace(
        name="Acme Analytics",
        primary_website="https://acme.example",
        description="Analytics for small shops",
        business_descriptions=["We make analytics simple."],
        preferred_anchors=["Acme analytics"],
        preferred_categories=["Business"],
        target_countries=["US"],
        contact_phone="+1 555 0100",
    )
    project = SimpleNamespace(
        name="Acme",
        target_website="https://acme.example",
        business_profile=profile,
    )
    website = SimpleNamespace(description="", anchor_text="")
    row = SimpleNamespace(email="inbox+abc@gmail.com")
    values = backlink_post.build_values(project, website, row)
    assert values["link"] == "https://acme.example"
    assert values["anchor"] == "Acme analytics"
    assert values["description"] == "We make analytics simple."
    assert values["name"] == "Acme Analytics"
    assert values["email"] == "inbox+abc@gmail.com"
    assert values["country"] == "US"


def test_a_link_is_only_reported_when_the_page_really_carries_it() -> None:
    html = '<a href="https://www.acme.example/lp">Acme</a>'
    assert backlink_post.linked_on_page(html, "https://acme.example") is True
    assert backlink_post.linked_on_page('<a href="/contact">Mail</a>', "https://acme.example") is False
    assert backlink_post.linked_on_page(html, "") is False


def test_the_signup_paths_cover_the_common_platforms() -> None:
    paths = site_accounts._signup_candidates("https://directory.example.org/add")
    for expected in (
        "/register",
        "/register.php",
        "/wp-login.php?action=register",
        "/users/sign_up",
        "/account/register",
        "/join",
    ):
        assert any(path.endswith(expected) for path in paths), paths


class _NoLinkPage:
    """A page with a form but without any URL / website field."""

    url = "https://directory.example.org/profile"

    def goto(self, *args, **kwargs) -> None:
        return None

    def wait_for_timeout(self, *args, **kwargs) -> None:
        return None

    def content(self) -> str:
        return "<html><body>profile</body></html>"

    def evaluate(self, script, arg=None):
        if script is backlink_post._COLLECT_JS:
            return {
                "fields": [
                    {
                        "selector": "#name",
                        "label": "Name",
                        "type": "text",
                        "required": False,
                    }
                ],
                "buttons": [{"text": "Save", "type": "submit"}],
                "title": "Profile",
                "url": self.url,
                "text": "Edit your profile",
            }
        return ""


def test_no_link_field_is_reported_instead_of_a_fake_post() -> None:
    result = backlink_post.post(
        _NoLinkPage(),
        target_url="https://directory.example.org/profile",
        values={"link": "https://acme.example", "name": "Acme"},
    )
    assert result["status"] == backlink_post.STATUS_NEEDS_HUMAN
    assert "no website / URL field" in result["message"]


def test_posting_without_a_target_says_so() -> None:
    result = backlink_post.post(None, target_url="", values={"link": "https://acme.example"})
    assert result["status"] == backlink_post.STATUS_NEEDS_HUMAN


def test_signup_entry_points_cover_links_and_modal_buttons() -> None:
    """A sign-up form can hide behind a link, a tab or a modal button."""

    class _Root:
        def __init__(self, found) -> None:
            self.found = found

        def evaluate(self, *args, **kwargs):
            return self.found

    class _Page(_Root):
        def __init__(self, found) -> None:
            super().__init__(found)
            self.main_frame = self
            self.frames = [self]

    page = _Page(
        ["https://site.example/register", "", "https://site.example/join"]
    )
    links, clickables = site_accounts._signup_entry_points(page)
    assert links == ["https://site.example/register", "https://site.example/join"]
    assert clickables == [page]


def test_alias_carries_the_website_name() -> None:
    token = gmail_otp.site_alias_token("https://www.itnegbuy.com/", "w1")
    assert token == "itnegbuy-com"
    alias = gmail_otp.alias_for("owner@gmail.com", token)
    assert alias == "owner+itnegbuy-com@gmail.com"


def test_alias_stays_mail_safe_and_short() -> None:
    token = gmail_otp.site_alias_token("Ünïcode & Spaces!!", "w1")
    assert token
    assert all(char.isalnum() or char == "-" for char in token)
    assert len(gmail_otp.site_alias_token("a" * 200, "w1")) <= 32
    # Nothing usable falls back to the random token, never an empty local part.
    assert gmail_otp.site_alias_token("", "w1")


def test_dot_alias_still_reaches_the_real_inbox() -> None:
    dotted = gmail_otp.dot_alias_for("itnegbuy+itnegbuy-com@gmail.com")
    local = dotted.split("@", 1)[0]
    assert "." in local
    # Gmail ignores dots: removing them gives back the real inbox local part.
    assert local.replace(".", "") == "itnegbuy"


def test_signup_never_fills_a_password_change_or_a_code() -> None:
    for field in (
        {"name": "current_password"},
        {"name": "change_password"},
        {"name": "otp", "placeholder": "Verification code"},
        {"name": "coupon_code"},
        {"name": "vat_number"},
        {"name": "fax"},
        {"name": "security_question"},
        {"name": "newsletter", "type": "checkbox"},
        {"name": "credit_card_number"},
        {"name": "how_did_you_hear"},
    ):
        assert site_accounts._skip_reason(field), field
    # The real sign-up fields are still filled.
    for field in (
        {"name": "email", "type": "email"},
        {"name": "username"},
        {"name": "password", "type": "password"},
        {"name": "password_confirm", "type": "password"},
        {"name": "first_name"},
        {"name": "company"},
    ):
        assert site_accounts._skip_reason(field) is None, field


def _plain_page(text: str) -> object:
    class Page:
        def query_selector(self, *_args: object) -> None:
            return None

        def inner_text(self, *_args: object) -> str:
            return text

    return Page()


def test_verification_prompt_is_recognised() -> None:
    assert site_accounts._verification_needed(
        _plain_page("Please verify your email address to continue.")
    )
    assert site_accounts._verification_needed(
        _plain_page("We sent you a confirmation link - check your inbox.")
    )
    assert not site_accounts._verification_needed(
        _plain_page("Welcome back, your account is ready.")
    )


def test_google_pages_are_recognised() -> None:
    class Popup:
        def __init__(self, url: str) -> None:
            self.url = url

    assert site_accounts._is_google_page(Popup("https://accounts.google.com/signin"))
    assert site_accounts._is_google_page(
        Popup("https://example.org/?gsi=accounts.google.com")
    )
    assert not site_accounts._is_google_page(Popup("https://directory.example.org/"))


class _CaptchaPage:
    """A tiny page stand-in: selector found, widget token configurable."""

    def __init__(self, *, solved: bool, marker: str = "recaptcha") -> None:
        self._solved = solved
        self._marker = marker

    def query_selector(self, selector: str, *_args: object) -> object | None:
        return object() if self._marker in selector else None

    def evaluate(self, script: str, *_args: object) -> bool:
        return self._solved

    def inner_text(self, *_args: object) -> str:
        return ""


def test_a_solved_captcha_is_not_reported_as_a_challenge() -> None:
    # The widget keeps its iframe after solving: the token decides, not the iframe.
    assert site_accounts._challenge(_CaptchaPage(solved=True)) is None
    assert site_accounts._challenge(_CaptchaPage(solved=False)) == "CAPTCHA"


def test_the_challenge_kind_is_named() -> None:
    assert (
        site_accounts._challenge_kind(_CaptchaPage(solved=False)) == "reCAPTCHA"
    )
    assert (
        site_accounts._challenge_kind(
            _CaptchaPage(solved=False, marker="turnstile")
        )
        == "Cloudflare Turnstile"
    )


def test_captcha_wait_is_on_by_default_and_can_be_turned_off(db_session) -> None:
    project = _project(db_session, "captcha-switch")
    assert site_accounts.signup_details(db_session, project.id)["captcha_wait"] is True
    saved = site_accounts.save_signup_details(
        db_session, project, captcha_wait=False
    )
    assert saved["captcha_wait"] is False
    assert site_accounts.signup_details(db_session, project.id)["captcha_wait"] is False


def test_turning_the_wait_off_stops_the_row_at_once(db_session) -> None:
    project = _project(db_session, "captcha-nowait")
    website = _website(db_session)
    row = site_accounts.ensure_account(db_session, project.id, website.id)
    started = datetime.now(UTC)
    done = site_accounts._wait_for_human(
        db_session,
        _CaptchaPage(solved=False),
        project,
        website,
        row,
        wait=False,
        seconds=0.1,
    )
    db_session.refresh(row)
    assert done is False
    assert row.status == site_accounts.STATUS_NEEDS_HUMAN
    assert "Retry" in (row.last_error or "")
    assert datetime.now(UTC) - started < timedelta(seconds=5)
