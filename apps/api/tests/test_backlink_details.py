"""The backlink details of a project live in one place: its business profile."""

from __future__ import annotations

from app.db.models import BusinessProfile, Project

API = "/api/v1"


def _project(client, **extra) -> dict:
    body = {"name": "Details project", "target_website": "https://details.example"}
    body.update(extra)
    response = client.post(f"{API}/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_project_can_be_created_with_its_backlink_details(authenticated_client, db_session) -> None:
    project = _project(
        authenticated_client,
        details={
            "company_name": "Acme Widgets",
            "description": "We make widgets for teams.",
            "email": "hello@acme.example",
            "phone": "+1 555 0100",
            "website": "acme.example",
            "address": "1 Main Street",
            "city": "Springfield",
            "state": "IL",
            "country": "US",
            "postal_code": "62701",
            "categories": ["Business", "Technology"],
            "founded_year": 2015,
            "employee_count": 24,
            "anchors": ["best widgets", "acme widgets"],
        },
    )

    details = authenticated_client.get(f"{API}/projects/{project['id']}/backlink-details")

    assert details.status_code == 200, details.text
    payload = details.json()
    assert payload["company_name"] == "Acme Widgets"
    assert payload["email"] == "hello@acme.example"
    assert payload["city"] == "Springfield"
    assert payload["founded_year"] == 2015
    assert payload["anchors"] == ["best widgets", "acme widgets"]
    assert payload["profile_id"]

    # The facts are stored once - in the business profile of the project.
    db_session.rollback()
    stored = db_session.get(Project, project["id"])
    assert stored.business_profile_id == payload["profile_id"]
    profile = db_session.get(BusinessProfile, payload["profile_id"])
    assert profile.name == "Acme Widgets"
    assert profile.preferred_anchors == ["best widgets", "acme widgets"]


def test_the_details_can_be_updated_without_touching_the_rest(authenticated_client) -> None:
    project = _project(
        authenticated_client,
        details={"company_name": "Acme Widgets", "email": "hello@acme.example", "city": "Springfield"},
    )

    response = authenticated_client.put(
        f"{API}/projects/{project['id']}/backlink-details",
        json={"phone": "+1 555 0199", "anchors": ["acme"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["phone"] == "+1 555 0199"
    assert payload["anchors"] == ["acme"]
    # The values that were not sent are still there.
    assert payload["company_name"] == "Acme Widgets"
    assert payload["city"] == "Springfield"


def test_patching_the_project_accepts_the_details(authenticated_client) -> None:
    project = _project(authenticated_client)

    response = authenticated_client.patch(
        f"{API}/projects/{project['id']}",
        json={"details": {"company_name": "Patched Ltd", "email": "hi@patched.example"}},
    )

    assert response.status_code == 200, response.text
    details = authenticated_client.get(f"{API}/projects/{project['id']}/backlink-details").json()
    assert details["company_name"] == "Patched Ltd"
    assert details["email"] == "hi@patched.example"
    assert details["profile_id"] is not None


def test_the_report_lists_the_fields_the_websites_ask_for(authenticated_client) -> None:
    project = _project(
        authenticated_client,
        details={"company_name": "Acme Widgets", "website": "https://acme.example"},
    )

    payload = authenticated_client.get(
        f"{API}/projects/{project['id']}/backlink-details"
    ).json()

    # Without any website the default set is reported.
    assert "company_name" in payload["required"]
    assert "company_name" in payload["filled"]
    # The description can be drafted from the profile, the e-mail cannot.
    assert "email" in payload["missing"]


def test_a_shared_profile_is_named_as_shared(authenticated_client) -> None:
    profile = authenticated_client.post(
        f"{API}/profiles",
        json={"name": "Shared profile", "primary_website": "https://shared.example"},
    )
    assert profile.status_code == 201, profile.text
    profile_id = profile.json()["id"]

    first = _project(authenticated_client, name="First", business_profile_id=profile_id)
    _project(authenticated_client, name="Second", business_profile_id=profile_id)

    payload = authenticated_client.get(f"{API}/projects/{first['id']}/backlink-details").json()

    assert payload["shared_with_projects"] == 2
    assert any("shared" in note.lower() for note in payload["notes"])

    # Writing through one project is visible in the other - there is one truth.
    authenticated_client.put(
        f"{API}/projects/{first['id']}/backlink-details",
        json={"company_name": "Renamed everywhere"},
    )
    other = authenticated_client.get(f"{API}/projects/{first['id']}/backlink-details").json()
    assert other["company_name"] == "Renamed everywhere"
    assert authenticated_client.get(f"{API}/profiles/{profile_id}").json()["name"] == "Renamed everywhere"


def test_the_gap_report_can_derive_the_address_from_the_profile(authenticated_client) -> None:
    project = _project(
        authenticated_client,
        details={
            "company_name": "Acme Widgets",
            "website": "https://acme.example",
            "address": "1 Main Street",
            "city": "Springfield",
            "postal_code": "62701",
        },
    )
    website = authenticated_client.post(
        f"{API}/websites",
        json={"opportunity_url": "https://address-gap.example/add", "name": "Address gap"},
    ).json()
    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "opportunity_url": website["opportunity_url"],
            "name": "Address gap",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project["id"],
        },
    )
    assert opportunity.status_code == 201, opportunity.text

    report = authenticated_client.get(
        f"{API}/opportunities/{opportunity.json()['id']}/details/gaps"
    )

    assert report.status_code == 200, report.text
    payload = report.json()
    # The profile now carries the address, so it is derivable (not "not derivable").
    reasons = {item["field"]: item["reason"] for item in payload["not_derivable"]}
    assert "address" not in reasons or "street address" not in reasons["address"]
