"""Site details tests: storing, reporting the missing fields and generating them.

The details of a submission are stored per opportunity.  The module never
invents a fact: a value is only written when it exists in the business
profile of the project or when the operator entered it.
"""

from __future__ import annotations

from app.db.models import SiteDetails
from tests.conftest import API


def _create_profile(client, **overrides) -> dict:
    payload = {
        "name": "Acme Analytics",
        "primary_website": "https://acme.example",
        "description": "Acme builds analytics tools for small teams.",
        "industry": "software",
        "contact_email": "hello@acme.example",
        "contact_phone": "+1 555 0100",
        "keywords": ["analytics", "dashboards"],
        "preferred_anchors": ["Acme Analytics"],
    }
    payload.update(overrides)
    response = client.post(f"{API}/profiles", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _attach_profile(client, project_id: str, profile_id: str) -> None:
    response = client.patch(
        f"{API}/projects/{project_id}", json={"business_profile_id": profile_id}
    )
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------
# Storing
# --------------------------------------------------------------------------
def test_details_can_be_stored_and_read(authenticated_client, opportunity_id) -> None:
    stored = authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details",
        json={
            "company_name": "Acme Analytics",
            "website": "https://acme.example",
            "description": "We build analytics tools.",
            "extra": {"pitch": "A directory listing for Acme."},
        },
    )

    assert stored.status_code == 200, stored.text
    body = stored.json()
    assert body["company_name"] == "Acme Analytics"
    assert body["website"] == "https://acme.example"
    assert body["extra"] == {"pitch": "A directory listing for Acme."}
    assert body["generated"] == {}

    read = authenticated_client.get(f"{API}/opportunities/{opportunity_id}/details")
    assert read.status_code == 200, read.text
    assert read.json()["company_name"] == "Acme Analytics"
    assert read.json()["opportunity_id"] == opportunity_id


def test_only_the_supplied_fields_are_changed(authenticated_client, opportunity_id) -> None:
    authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details",
        json={"company_name": "Acme Analytics", "email": "hello@acme.example"},
    )

    updated = authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details", json={"city": "Berlin"}
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["company_name"] == "Acme Analytics"
    assert updated.json()["email"] == "hello@acme.example"
    assert updated.json()["city"] == "Berlin"


def test_missing_details_are_reported_as_empty(
    authenticated_client, opportunity_id
) -> None:
    """An opportunity without details is not an error - the record is empty."""
    response = authenticated_client.get(f"{API}/opportunities/{opportunity_id}/details")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["company_name"] is None
    assert body["extra"] == {}
    assert body["missing"]
    assert body["complete"] is False


def test_the_details_can_be_deleted(authenticated_client, opportunity_id, db_session) -> None:
    authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details", json={"company_name": "Acme"}
    )

    response = authenticated_client.delete(f"{API}/opportunities/{opportunity_id}/details")

    assert response.status_code == 204, response.text
    db_session.rollback()
    assert db_session.query(SiteDetails).count() == 0


def test_the_details_of_a_foreign_opportunity_are_not_readable(
    authenticated_client, other_auth_headers
) -> None:
    their_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Foreign project", "target_website": "https://foreign.example"},
        headers=other_auth_headers,
    )
    assert their_project.status_code == 201, their_project.text
    theirs = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Foreign directory",
            "opportunity_url": "https://foreign.example.org/add",
            "project_id": their_project.json()["id"],
        },
        headers=other_auth_headers,
    )
    assert theirs.status_code == 201, theirs.text

    response = authenticated_client.get(
        f"{API}/opportunities/{theirs.json()['id']}/details"
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"


# --------------------------------------------------------------------------
# The required fields
# --------------------------------------------------------------------------
def test_the_required_endpoint_reports_the_missing_fields(
    authenticated_client, opportunity_id
) -> None:
    response = authenticated_client.get(
        f"{API}/opportunities/{opportunity_id}/details/required"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False
    assert {"name", "website", "description"} <= set(body["required"])
    assert {"name", "website", "description"} <= set(body["missing"])
    # The labels are human readable.
    assert body["labels"]["name"] == "Company name"
    assert all(body["labels"].values())


def test_the_details_become_complete_once_they_are_filled(
    authenticated_client, opportunity_id
) -> None:
    authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details",
        json={
            "company_name": "Acme Analytics",
            "website": "https://acme.example",
            "description": "We build analytics tools.",
        },
    )

    response = authenticated_client.get(
        f"{API}/opportunities/{opportunity_id}/details/required"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["missing"] == []
    assert body["complete"] is True


def test_a_field_of_the_extra_object_counts_as_filled(
    authenticated_client, opportunity_id
) -> None:
    authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details",
        json={
            "company_name": "Acme Analytics",
            "website": "https://acme.example",
            "description": "We build analytics tools.",
            "extra": {"author_bio": "The team behind Acme."},
        },
    )

    response = authenticated_client.get(
        f"{API}/opportunities/{opportunity_id}/details/required"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "author_bio" not in body["missing"]


# --------------------------------------------------------------------------
# The generation
# --------------------------------------------------------------------------
def test_generating_fills_the_empty_fields_from_the_profile(
    authenticated_client, project_id, opportunity_id
) -> None:
    profile = _create_profile(authenticated_client)
    _attach_profile(authenticated_client, project_id, profile["id"])

    response = authenticated_client.post(
        f"{API}/opportunities/{opportunity_id}/details/generate"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    details = body["details"]
    assert details["company_name"] == "Acme Analytics"
    assert details["email"] == "hello@acme.example"
    assert details["phone"] == "+1 555 0100"
    assert details["website"] == "https://acme.example"
    assert details["description"]
    assert "company_name" in body["generated"]
    assert "description" in body["generated"]
    assert body["source"] in ("ai", "profile")


def test_generating_never_invents_a_fact(
    authenticated_client, project_id, opportunity_id
) -> None:
    profile = _create_profile(
        authenticated_client,
        contact_phone=None,
        contact_email=None,
        keywords=[],
    )
    _attach_profile(authenticated_client, project_id, profile["id"])

    response = authenticated_client.post(
        f"{API}/opportunities/{opportunity_id}/details/generate"
    )

    assert response.status_code == 200, response.text
    details = response.json()["details"]
    # Nothing that is not part of the profile is written.
    assert details["phone"] is None
    assert details["email"] is None
    assert details["address"] is None
    assert details["city"] is None
    assert details["postal_code"] is None
    assert details["founded_year"] is None
    assert details["employee_count"] is None
    assert details["country"] is None
    assert details["state"] is None
    # The description only restates the profile.
    assert "Acme" in details["description"]


def test_generating_keeps_the_values_of_the_operator(
    authenticated_client, project_id, opportunity_id
) -> None:
    profile = _create_profile(authenticated_client)
    _attach_profile(authenticated_client, project_id, profile["id"])
    authenticated_client.put(
        f"{API}/opportunities/{opportunity_id}/details",
        json={"company_name": "The Manual Name", "description": "The manual description."},
    )

    response = authenticated_client.post(
        f"{API}/opportunities/{opportunity_id}/details/generate"
    )

    assert response.status_code == 200, response.text
    details = response.json()["details"]
    assert details["company_name"] == "The Manual Name"
    assert details["description"] == "The manual description."
    assert "company_name" not in response.json()["generated"]


def test_generating_without_a_profile_does_not_fail(
    authenticated_client, opportunity_id
) -> None:
    response = authenticated_client.post(
        f"{API}/opportunities/{opportunity_id}/details/generate"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["details"]["company_name"] is None
    assert body["details"]["email"] is None
    # Without any profile there is no description to write.
    assert body["details"]["description"] is None
    assert "company_name" not in body["generated"]
    assert "description" not in body["generated"]
