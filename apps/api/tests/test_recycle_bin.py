"""The recycle bin: everything that is deleted waits until it is restored or purged."""

from __future__ import annotations

from app.db.models import BusinessProfile, Opportunity, Project, Task, Website

API = "/api/v1"


def _project(client, name: str = "Recycle project") -> dict:
    response = client.post(
        f"{API}/projects",
        json={"name": name, "target_website": "https://recycle.example"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _website(client, domain: str = "recycle-bin.example") -> dict:
    response = client.post(
        f"{API}/websites",
        json={"opportunity_url": f"https://{domain}/add", "name": "Recycle site"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bin(client) -> dict:
    response = client.get(f"{API}/recycle-bin")
    assert response.status_code == 200, response.text
    return response.json()


def _kinds(payload: dict) -> list[tuple[str, str]]:
    return [(item["kind"], item["id"]) for item in payload["items"]]


def test_a_deleted_project_waits_in_the_recycle_bin(authenticated_client) -> None:
    project = _project(authenticated_client)

    assert authenticated_client.delete(f"{API}/projects/{project['id']}").status_code == 204

    payload = _bin(authenticated_client)
    assert ("project", project["id"]) in _kinds(payload)
    assert payload["counts"]["project"] >= 1
    assert authenticated_client.get(f"{API}/projects").json()["total"] >= 0
    assert authenticated_client.get(f"{API}/projects/{project['id']}").status_code == 404


def test_a_project_of_the_bin_can_be_restored(authenticated_client, db_session) -> None:
    project = _project(authenticated_client)
    authenticated_client.delete(f"{API}/projects/{project['id']}")

    response = authenticated_client.post(
        f"{API}/recycle-bin/project/{project['id']}/restore"
    )

    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "project"
    assert authenticated_client.get(f"{API}/projects/{project['id']}").status_code == 200
    db_session.rollback()
    assert db_session.get(Project, project["id"]).deleted_at is None


def test_deleting_a_project_forever_removes_it_and_its_opportunities(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    website = _website(authenticated_client)
    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "opportunity_url": website["opportunity_url"],
            "name": "Recycle site",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project["id"],
        },
    )
    assert opportunity.status_code == 201, opportunity.text

    authenticated_client.delete(f"{API}/projects/{project['id']}")
    response = authenticated_client.delete(f"{API}/recycle-bin/project/{project['id']}")

    assert response.status_code == 204, response.text
    db_session.rollback()
    assert db_session.get(Project, project["id"]) is None
    assert db_session.query(Opportunity).filter_by(project_id=project["id"]).count() == 0
    # The website itself stays - it belongs to the central list, not to the project.
    assert db_session.get(Website, website["id"]) is not None


def test_a_deleted_website_waits_in_the_bin_and_can_be_restored(authenticated_client) -> None:
    website = _website(authenticated_client)

    assert authenticated_client.delete(f"{API}/websites/{website['id']}").status_code == 204

    payload = _bin(authenticated_client)
    assert ("website", website["id"]) in _kinds(payload)
    assert payload["counts"]["website"] >= 1

    restored = authenticated_client.post(f"{API}/recycle-bin/website/{website['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["kind"] == "website"
    listing = authenticated_client.get(f"{API}/websites", params={"status": "ACTIVE"})
    assert any(item["id"] == website["id"] for item in listing.json()["items"])


def test_deleting_a_website_forever_removes_it(authenticated_client, db_session) -> None:
    website = _website(authenticated_client, "purge-bin.example")
    authenticated_client.delete(f"{API}/websites/{website['id']}")

    response = authenticated_client.delete(f"{API}/recycle-bin/website/{website['id']}")

    assert response.status_code == 204, response.text
    db_session.rollback()
    assert db_session.get(Website, website["id"]) is None


def test_a_deleted_opportunity_waits_in_the_bin(authenticated_client, project_id, db_session) -> None:
    website = _website(authenticated_client, "opp-bin.example")
    created = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "opportunity_url": website["opportunity_url"],
            "name": "Recycle site",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    )
    assert created.status_code == 201, created.text
    opportunity_id = created.json()["id"]

    response = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": [opportunity_id], "action": "delete"},
    )
    assert response.status_code == 200, response.text

    payload = _bin(authenticated_client)
    assert ("opportunity", opportunity_id) in _kinds(payload)
    assert authenticated_client.get(f"{API}/opportunities/{opportunity_id}").status_code == 404

    restored = authenticated_client.post(
        f"{API}/recycle-bin/opportunity/{opportunity_id}/restore"
    )
    assert restored.status_code == 200, restored.text
    assert authenticated_client.get(f"{API}/opportunities/{opportunity_id}").status_code == 200
    db_session.rollback()
    assert db_session.get(Opportunity, opportunity_id).deleted_at is None


def test_removing_an_opportunity_cancels_its_open_tasks(
    authenticated_client, project_id, db_session
) -> None:
    website = _website(authenticated_client, "cancel-bin.example")
    created = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "opportunity_url": website["opportunity_url"],
            "name": "Recycle site",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    ).json()
    queued = authenticated_client.post(
        f"{API}/queue",
        json={"project_id": project_id, "opportunity_ids": [created["id"]], "type": "SUBMIT"},
    )
    assert queued.status_code == 200, queued.text

    authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": [created["id"]], "action": "delete"},
    )

    db_session.rollback()
    tasks = db_session.query(Task).filter_by(opportunity_id=created["id"]).all()
    assert tasks
    assert all(task.status == "CANCELLED" for task in tasks)


def test_a_deleted_profile_waits_in_the_bin_and_the_projects_keep_working(
    authenticated_client, db_session
) -> None:
    profile = authenticated_client.post(
        f"{API}/profiles",
        json={"name": "Recycle profile", "primary_website": "https://profile.example"},
    )
    assert profile.status_code == 201, profile.text
    project = authenticated_client.post(
        f"{API}/projects",
        json={
            "name": "Profile project",
            "target_website": "https://profile.example",
            "business_profile_id": profile.json()["id"],
        },
    )
    assert project.status_code == 201, project.text

    assert authenticated_client.delete(f"{API}/profiles/{profile.json()['id']}").status_code == 204

    payload = _bin(authenticated_client)
    assert ("profile", profile.json()["id"]) in _kinds(payload)
    # The project still exists and keeps its reference for a later restore.
    assert authenticated_client.get(f"{API}/projects/{project.json()['id']}").status_code == 200

    restored = authenticated_client.post(
        f"{API}/recycle-bin/profile/{profile.json()['id']}/restore"
    )
    assert restored.status_code == 200, restored.text
    assert authenticated_client.get(f"{API}/profiles/{profile.json()['id']}").status_code == 200

    authenticated_client.delete(f"{API}/profiles/{profile.json()['id']}")
    purged = authenticated_client.delete(
        f"{API}/recycle-bin/profile/{profile.json()['id']}"
    )
    assert purged.status_code == 204, purged.text
    db_session.rollback()
    assert db_session.get(BusinessProfile, profile.json()["id"]) is None
    assert db_session.get(Project, project.json()["id"]).business_profile_id is None


def test_the_bin_can_be_filtered_by_kind(authenticated_client) -> None:
    project = _project(authenticated_client, "Filtered bin project")
    website = _website(authenticated_client, "filter-bin.example")
    authenticated_client.delete(f"{API}/projects/{project['id']}")
    authenticated_client.delete(f"{API}/websites/{website['id']}")

    only_websites = authenticated_client.get(f"{API}/recycle-bin", params={"kind": "website"})
    assert only_websites.status_code == 200, only_websites.text
    assert all(item["kind"] == "website" for item in only_websites.json()["items"])
    assert only_websites.json()["total"] >= 1

    unknown = authenticated_client.get(f"{API}/recycle-bin", params={"kind": "spaceship"})
    assert unknown.status_code == 404


def test_the_counts_endpoint_reports_every_kind(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/recycle-bin/counts")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"project", "website", "profile", "opportunity"}
    assert all(isinstance(value, int) for value in payload.values())


def test_another_owner_cannot_touch_the_bin_of_someone_else(
    authenticated_client, other_auth_headers
) -> None:
    project = _project(authenticated_client, "Private bin project")
    authenticated_client.delete(f"{API}/projects/{project['id']}")

    payload = authenticated_client.get(f"{API}/recycle-bin", headers=other_auth_headers).json()
    assert ("project", project["id"]) not in _kinds(payload)

    restore = authenticated_client.post(
        f"{API}/recycle-bin/project/{project['id']}/restore",
        headers=other_auth_headers,
    )
    assert restore.status_code in (403, 404)
    purge = authenticated_client.delete(
        f"{API}/recycle-bin/project/{project['id']}",
        headers=other_auth_headers,
    )
    assert purge.status_code in (403, 404)


def test_an_unknown_row_is_not_in_the_bin(authenticated_client) -> None:
    response = authenticated_client.post(f"{API}/recycle-bin/project/does-not-exist/restore")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
