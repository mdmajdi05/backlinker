"""Project tests: creation, settings, slug uniqueness, deletion and isolation."""

from __future__ import annotations

from app.db.models import Project, ProjectSettings, TargetWebsite
from tests.conftest import API


def test_create_project_with_settings_and_landing_pages(
    authenticated_client, db_session
) -> None:
    response = authenticated_client.post(
        f"{API}/projects",
        json={
            "name": "Acme Backlinks",
            "description": "Spring campaign",
            "target_website": "acme.example",
            "settings": {
                "max_concurrency": 2,
                "request_rate_per_minute": 20,
                "require_approval": False,
            },
            "landing_pages": [
                {"name": "Product", "url": "https://acme.example/product"},
                {"name": "Pricing", "url": "https://acme.example/pricing", "kind": "LANDING"},
            ],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Acme Backlinks"
    assert body["slug"] == "acme-backlinks"
    assert body["target_website"] == "https://acme.example"
    assert body["status"] == "ACTIVE"
    assert body["version"] == 1
    assert body["settings"]["max_concurrency"] == 2
    assert body["settings"]["request_rate_per_minute"] == 20
    assert body["settings"]["require_approval"] is False
    assert body["counts"] == {
        "opportunities": 0,
        "approved": 0,
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "verified_live": 0,
        "pending_manual": 0,
    }

    db_session.rollback()
    landing_pages = (
        db_session.query(TargetWebsite)
        .filter(TargetWebsite.project_id == body["id"])
        .order_by(TargetWebsite.name)
        .all()
    )
    assert [page.url for page in landing_pages] == [
        "https://acme.example/pricing",
        "https://acme.example/product",
    ]
    assert {page.domain for page in landing_pages} == {"acme.example"}


def test_create_project_requires_a_name_and_a_target_website(authenticated_client) -> None:
    missing_name = authenticated_client.post(
        f"{API}/projects", json={"target_website": "https://acme.example"}
    )
    missing_website = authenticated_client.post(f"{API}/projects", json={"name": "Acme"})
    short_website = authenticated_client.post(
        f"{API}/projects", json={"name": "Acme", "target_website": "ab"}
    )

    assert missing_name.status_code == 422
    assert missing_website.status_code == 422
    assert short_website.status_code == 422


def test_duplicate_project_name_gets_a_slug_suffix(authenticated_client) -> None:
    first = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Acme Backlinks", "target_website": "https://acme.example"},
    )
    second = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Acme Backlinks", "target_website": "https://acme.example"},
    )
    third = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Acme Backlinks", "target_website": "https://acme.example"},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert third.status_code == 201, third.text
    assert first.json()["slug"] == "acme-backlinks"
    assert second.json()["slug"] == "acme-backlinks-2"
    assert third.json()["slug"] == "acme-backlinks-3"
    assert len({first.json()["id"], second.json()["id"], third.json()["id"]}) == 3


def test_get_project_returns_the_settings_and_counts(authenticated_client, project_id) -> None:
    response = authenticated_client.get(f"{API}/projects/{project_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == project_id
    assert body["settings"]["max_concurrency"] == 3
    assert body["counts"]["opportunities"] == 0


def test_update_project(authenticated_client, project_id) -> None:
    response = authenticated_client.patch(
        f"{API}/projects/{project_id}",
        json={
            "name": "Acme Backlinks 2026",
            "description": "Updated description",
            "target_website": "https://acme.example",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Acme Backlinks 2026"
    assert body["description"] == "Updated description"
    assert body["version"] == 2
    assert body["slug"] == "acme-backlinks"


def test_update_project_settings(authenticated_client, project_id, db_session) -> None:
    response = authenticated_client.put(
        f"{API}/projects/{project_id}/settings",
        json={
            "max_concurrency": 7,
            "global_concurrency": 12,
            "per_domain_concurrency": 2,
            "request_rate_per_minute": 45,
            "max_retries": 5,
            "backoff_base_seconds": 10,
            "jitter_seconds": 2,
            "daily_discovery_limit": 250,
            "require_approval": False,
            "auto_queue_approved": True,
            "timezone": "Europe/Berlin",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == project_id
    assert body["max_concurrency"] == 7
    assert body["global_concurrency"] == 12
    assert body["request_rate_per_minute"] == 45
    assert body["backoff_base_seconds"] == 10
    assert body["auto_queue_approved"] is True
    assert body["timezone"] == "Europe/Berlin"

    db_session.rollback()
    stored = db_session.query(ProjectSettings).filter_by(project_id=project_id).one()
    assert stored.max_concurrency == 7
    assert stored.backoff_base_seconds == 10


def test_delete_project(authenticated_client, project_id, db_session) -> None:
    response = authenticated_client.delete(f"{API}/projects/{project_id}")

    assert response.status_code == 204, response.text
    assert authenticated_client.get(f"{API}/projects/{project_id}").status_code == 404

    # The project is not thrown away - it waits in the recycle bin.
    db_session.rollback()
    stored = db_session.get(Project, project_id)
    assert stored is not None
    assert stored.deleted_at is not None
    assert authenticated_client.get(f"{API}/recycle-bin").json()["counts"]["project"] >= 1


def test_listing_is_scoped_to_the_owner(authenticated_client, other_auth_headers) -> None:
    mine = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Acme Backlinks", "target_website": "https://acme.example"},
    ).json()
    theirs = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Other Backlinks", "target_website": "https://other.example"},
        headers=other_auth_headers,
    ).json()

    listing = authenticated_client.get(f"{API}/projects")
    assert listing.status_code == 200, listing.text
    ids = [item["id"] for item in listing.json()["items"]]
    assert mine["id"] in ids
    assert theirs["id"] not in ids


def test_another_owner_cannot_read_a_project(authenticated_client, other_auth_headers) -> None:
    mine = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Acme Backlinks", "target_website": "https://acme.example"},
    ).json()

    response = authenticated_client.get(f"{API}/projects/{mine['id']}", headers=other_auth_headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"


def test_another_owner_cannot_modify_a_project(authenticated_client, other_auth_headers) -> None:
    mine = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Acme Backlinks", "target_website": "https://acme.example"},
    ).json()

    patched = authenticated_client.patch(
        f"{API}/projects/{mine['id']}",
        json={"name": "Hijacked", "target_website": "https://acme.example"},
        headers=other_auth_headers,
    )
    deleted = authenticated_client.delete(
        f"{API}/projects/{mine['id']}", headers=other_auth_headers
    )
    settings = authenticated_client.put(
        f"{API}/projects/{mine['id']}/settings",
        json={"max_concurrency": 50},
        headers=other_auth_headers,
    )

    assert patched.status_code == 403, patched.text
    assert deleted.status_code == 403, deleted.text
    assert settings.status_code == 403, settings.text


def test_unknown_project_returns_404(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/projects/does-not-exist")

    assert response.status_code == 404, response.text
