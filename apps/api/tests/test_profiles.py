"""Business profile tests: validation, ownership and lifecycle."""

from __future__ import annotations

from app.db.models import BusinessProfile
from tests.conftest import API

PROFILE_PAYLOAD = {
    "name": "Acme Analytics",
    "primary_website": "acme-analytics.example",
    "description": "Analytics platform for ecommerce teams",
    "industry": "SaaS",
    "niche": "ecommerce analytics",
    "keywords": ["ecommerce analytics", "shopify reporting"],
    "preferred_anchors": ["Acme Analytics"],
    "target_countries": ["US", "GB"],
}


def _create(client, payload=None, headers=None) -> dict:
    response = client.post(
        f"{API}/profiles", json=payload or PROFILE_PAYLOAD, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_profile_returns_201(authenticated_client) -> None:
    body = _create(authenticated_client)

    assert body["name"] == "Acme Analytics"
    assert body["primary_website"] == "https://acme-analytics.example"
    assert body["industry"] == "SaaS"
    assert body["target_countries"] == ["US", "GB"]
    assert body["preferred_anchors"] == ["Acme Analytics"]
    assert body["id"]


def test_create_profile_requires_name_and_website(authenticated_client) -> None:
    missing_name = authenticated_client.post(
        f"{API}/profiles",
        json={"primary_website": "https://acme-analytics.example"},
    )
    missing_website = authenticated_client.post(
        f"{API}/profiles",
        json={"name": "Acme Analytics"},
    )
    too_short_website = authenticated_client.post(
        f"{API}/profiles",
        json={"name": "Acme Analytics", "primary_website": "ab"},
    )
    empty_name = authenticated_client.post(
        f"{API}/profiles",
        json={"name": "", "primary_website": "https://acme-analytics.example"},
    )

    assert missing_name.status_code == 422
    assert missing_website.status_code == 422
    assert too_short_website.status_code == 422
    assert empty_name.status_code == 422


def test_duplicate_profile_name_for_the_same_owner_returns_409(authenticated_client) -> None:
    _create(authenticated_client)

    duplicate = authenticated_client.post(f"{API}/profiles", json=PROFILE_PAYLOAD)

    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "duplicate"


def test_duplicate_profile_name_for_another_owner_is_allowed(
    authenticated_client, other_auth_headers
) -> None:
    _create(authenticated_client)

    other = authenticated_client.post(
        f"{API}/profiles",
        json=PROFILE_PAYLOAD,
        headers=other_auth_headers,
    )

    assert other.status_code == 201, other.text


def test_update_profile(authenticated_client) -> None:
    profile = _create(authenticated_client)

    response = authenticated_client.put(
        f"{API}/profiles/{profile['id']}",
        json={
            "name": "Acme Analytics EU",
            "primary_website": "https://eu.acme-analytics.example",
            "description": "European analytics platform",
            "industry": "SaaS",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Acme Analytics EU"
    assert body["primary_website"] == "https://eu.acme-analytics.example"
    assert body["description"] == "European analytics platform"

    fetched = authenticated_client.get(f"{API}/profiles/{profile['id']}")
    assert fetched.json()["name"] == "Acme Analytics EU"


def test_delete_profile(authenticated_client, db_session) -> None:
    profile = _create(authenticated_client)

    response = authenticated_client.delete(f"{API}/profiles/{profile['id']}")

    assert response.status_code == 204, response.text
    assert authenticated_client.get(f"{API}/profiles/{profile['id']}").status_code == 404
    db_session.rollback()
    assert db_session.get(BusinessProfile, profile["id"]) is None


def test_listing_is_scoped_to_the_owner(authenticated_client, other_auth_headers) -> None:
    mine = _create(authenticated_client)
    theirs = _create(authenticated_client, headers=other_auth_headers)

    listing = authenticated_client.get(f"{API}/profiles")
    assert listing.status_code == 200, listing.text
    ids = [item["id"] for item in listing.json()]
    assert mine["id"] in ids
    assert theirs["id"] not in ids


def test_another_owner_cannot_read_a_profile(authenticated_client, other_auth_headers) -> None:
    mine = _create(authenticated_client)

    response = authenticated_client.get(f"{API}/profiles/{mine['id']}", headers=other_auth_headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"


def test_another_owner_cannot_update_a_profile(authenticated_client, other_auth_headers) -> None:
    mine = _create(authenticated_client)

    response = authenticated_client.put(
        f"{API}/profiles/{mine['id']}",
        json={"name": "Hijacked", "primary_website": "https://hijacked.example"},
        headers=other_auth_headers,
    )

    assert response.status_code == 403, response.text


def test_another_owner_cannot_delete_a_profile(authenticated_client, other_auth_headers) -> None:
    mine = _create(authenticated_client)

    response = authenticated_client.delete(
        f"{API}/profiles/{mine['id']}", headers=other_auth_headers
    )

    assert response.status_code == 403, response.text
