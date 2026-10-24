"""Registry tests: manual opportunities, deduplication, bulk actions and search."""

from __future__ import annotations

from app.db.models import Opportunity, Task, Website
from tests.conftest import API


def _create_opportunity(client, url: str, project_id: str, headers=None, **extra) -> dict:
    payload = {
        "name": "Directory Example",
        "opportunity_url": url,
        "category": "BUSINESS_DIRECTORY",
        "project_id": project_id,
    }
    payload.update(extra)
    response = client.post(f"{API}/opportunities", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_manual_opportunity(authenticated_client, project_id) -> None:
    body = _create_opportunity(
        authenticated_client,
        "https://directory.example.org/add-your-business",
        project_id,
        anchor_text="Acme Analytics",
    )

    assert body["project_id"] == project_id
    assert body["domain"] == "directory.example.org"
    assert body["opportunity_url"] == "https://directory.example.org/add-your-business"
    assert body["category"] == "BUSINESS_DIRECTORY"
    assert body["discovery_source"] == "manual"
    assert body["status"] == "NEEDS_REVIEW"
    assert body["anchor_text"] == "Acme Analytics"
    assert body["backlink_status"] == "PENDING"


def test_duplicate_opportunity_reuses_the_same_website(
    authenticated_client, project_id, db_session
) -> None:
    first = _create_opportunity(
        authenticated_client, "https://directory.example.org/add", project_id
    )
    second = _create_opportunity(
        authenticated_client, "https://Directory.Example.org/add/", project_id
    )

    assert first["id"] == second["id"]

    db_session.rollback()
    assert db_session.query(Website).count() == 1
    assert db_session.query(Opportunity).count() == 1


def test_the_same_website_can_be_linked_to_two_projects(
    authenticated_client, project_id, db_session
) -> None:
    other_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Second Campaign", "target_website": "https://second.example"},
    ).json()

    first = _create_opportunity(
        authenticated_client, "https://directory.example.org/add", project_id
    )
    second = _create_opportunity(
        authenticated_client, "https://directory.example.org/add", other_project["id"]
    )

    assert first["id"] != second["id"]
    db_session.rollback()
    assert db_session.query(Website).count() == 1
    assert db_session.query(Opportunity).count() == 2


def test_bulk_approve_reject_and_exclude(authenticated_client, project_id) -> None:
    ids = [
        _create_opportunity(
            authenticated_client, f"https://directory{index}.example.org/add", project_id
        )["id"]
        for index in range(3)
    ]

    approved = authenticated_client.post(
        f"{API}/opportunities/bulk", json={"opportunity_ids": ids[:2], "action": "approve"}
    )
    rejected = authenticated_client.post(
        f"{API}/opportunities/bulk", json={"opportunity_ids": [ids[2]], "action": "reject"}
    )
    excluded = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={
            "opportunity_ids": [ids[2]],
            "action": "exclude",
            "reason": "not relevant",
            "excluded_until": "2030-01-01T00:00:00",
        },
    )

    assert approved.status_code == 200, approved.text
    assert approved.json()["affected"] == 2
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["affected"] == 1
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["affected"] == 1

    listing = authenticated_client.get(f"{API}/opportunities", params={"project_id": project_id})
    statuses = {item["id"]: item["status"] for item in listing.json()["items"]}
    assert statuses[ids[0]] == "APPROVED"
    assert statuses[ids[1]] == "APPROVED"
    assert statuses[ids[2]] == "EXCLUDED"


def test_bulk_delete_removes_the_opportunity(authenticated_client, project_id, db_session) -> None:
    opportunity = _create_opportunity(
        authenticated_client, "https://directory.example.org/add", project_id
    )

    response = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": [opportunity["id"]], "action": "delete"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["affected"] == 1
    assert (
        authenticated_client.get(f"{API}/opportunities/{opportunity['id']}").status_code == 404
    )

    # The opportunity waits in the recycle bin and the website stays in the
    # central list (other projects may still use it).
    db_session.rollback()
    stored = db_session.query(Opportunity).one()
    assert stored.deleted_at is not None
    assert db_session.query(Website).count() == 1


def test_bulk_action_on_unknown_ids_affects_nothing(authenticated_client) -> None:
    response = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": ["does-not-exist"], "action": "approve"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["affected"] == 0


def test_bulk_queue_approves_and_queues_each_opportunity_once(
    authenticated_client, db_session, project_id
) -> None:
    ids = [
        _create_opportunity(
            authenticated_client, f"https://queue{index}.example.org/add", project_id
        )["id"]
        for index in range(2)
    ]

    first = authenticated_client.post(
        f"{API}/opportunities/bulk", json={"opportunity_ids": ids, "action": "queue"}
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"affected": 2, "queued": 2, "skipped": 0}

    db_session.rollback()
    tasks = db_session.query(Task).filter(Task.type == "SUBMIT").all()
    assert len(tasks) == 2
    assert {task.opportunity_id for task in tasks} == set(ids)
    assert all(task.status == "QUEUED" for task in tasks)
    statuses = {item.id: item.status for item in db_session.query(Opportunity).all()}
    assert statuses == {ids[0]: "QUEUED", ids[1]: "QUEUED"}

    # The second call is honest: nothing was queued again, everything was
    # skipped because an open submission task already exists.
    second = authenticated_client.post(
        f"{API}/opportunities/bulk", json={"opportunity_ids": ids, "action": "queue"}
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"affected": 0, "queued": 0, "skipped": 2}

    db_session.rollback()
    assert db_session.query(Task).filter(Task.type == "SUBMIT").count() == 2


def test_bulk_queue_skips_the_opportunities_of_a_paused_project(
    authenticated_client, db_session, project_id
) -> None:
    opportunity = _create_opportunity(
        authenticated_client, "https://paused-queue.example.org/add", project_id
    )
    paused = authenticated_client.patch(
        f"{API}/projects/{project_id}", json={"status": "PAUSED"}
    )
    assert paused.status_code == 200, paused.text

    response = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": [opportunity["id"]], "action": "queue"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"affected": 0, "queued": 0, "skipped": 1}
    db_session.rollback()
    assert db_session.query(Task).count() == 0


def test_update_opportunity(authenticated_client, opportunity_id) -> None:
    response = authenticated_client.patch(
        f"{API}/opportunities/{opportunity_id}",
        json={"name": "Renamed Directory", "notes": "call them tomorrow"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Renamed Directory"
    assert body["notes"] == "call them tomorrow"
    assert body["version"] >= 2


def test_search_filter_and_pagination(authenticated_client, project_id) -> None:
    _create_opportunity(authenticated_client, "https://alpha.example.org/add", project_id)
    _create_opportunity(authenticated_client, "https://beta.example.org/add", project_id)
    _create_opportunity(
        authenticated_client,
        "https://gamma.example.org/add",
        project_id,
        category="GUEST_POST",
    )

    search = authenticated_client.get(f"{API}/opportunities", params={"search": "alpha"})
    filtered = authenticated_client.get(f"{API}/opportunities", params={"category": "GUEST_POST"})
    by_domain = authenticated_client.get(f"{API}/opportunities", params={"domain": "beta"})
    scoped = authenticated_client.get(
        f"{API}/opportunities", params={"project_id": project_id, "page_size": 2, "page": 1}
    )
    second_page = authenticated_client.get(
        f"{API}/opportunities", params={"project_id": project_id, "page_size": 2, "page": 2}
    )

    assert search.json()["total"] == 1
    assert search.json()["items"][0]["domain"] == "alpha.example.org"
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["category"] == "GUEST_POST"
    assert by_domain.json()["total"] == 1
    assert by_domain.json()["items"][0]["domain"] == "beta.example.org"

    assert scoped.json()["total"] == 3
    assert scoped.json()["page"] == 1
    assert scoped.json()["page_size"] == 2
    assert scoped.json()["pages"] == 2
    assert len(scoped.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 1


def test_score_breakdown_is_exposed_when_present(
    authenticated_client, opportunity_id, db_session
) -> None:
    db_session.rollback()
    opportunity = db_session.get(Opportunity, opportunity_id)
    website = db_session.get(Website, opportunity.website_id)
    website.score = 82.5
    website.score_breakdown = {"relevance": 0.8, "authority": 0.55, "spam_score": 0.05}
    db_session.commit()

    response = authenticated_client.get(f"{API}/opportunities/{opportunity_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == 82.5
    assert body["score_breakdown"] == {
        "relevance": 0.8,
        "authority": 0.55,
        "spam_score": 0.05,
    }


def test_score_breakdown_is_none_when_it_is_empty(authenticated_client, opportunity_id) -> None:
    response = authenticated_client.get(f"{API}/opportunities/{opportunity_id}")

    assert response.status_code == 200, response.text
    assert response.json()["score_breakdown"] is None


def test_registry_listing_is_scoped_to_the_owner(
    authenticated_client, other_auth_headers, project_id
) -> None:
    # The second user owns a different project - their opportunity must not
    # show up in the listing of the first user.
    their_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Other project", "target_website": "https://other.example"},
        headers=other_auth_headers,
    )
    assert their_project.status_code == 201, their_project.text

    theirs = _create_opportunity(
        authenticated_client,
        "https://secret.example.org/add",
        their_project.json()["id"],
        headers=other_auth_headers,
    )

    listing = authenticated_client.get(f"{API}/opportunities")
    ids = [item["id"] for item in listing.json()["items"]]

    assert theirs["id"] not in ids


def test_a_foreign_opportunity_cannot_be_read_or_modified(
    authenticated_client, other_auth_headers
) -> None:
    their_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Foreign project", "target_website": "https://foreign.example"},
        headers=other_auth_headers,
    )
    assert their_project.status_code == 201, their_project.text

    theirs = _create_opportunity(
        authenticated_client,
        "https://foreign.example.org/add",
        their_project.json()["id"],
        headers=other_auth_headers,
    )

    read = authenticated_client.get(f"{API}/opportunities/{theirs['id']}")
    assert read.status_code == 403, read.text

    patch = authenticated_client.patch(
        f"{API}/opportunities/{theirs['id']}",
        json={"notes": "hijacked"},
    )
    assert patch.status_code == 403, patch.text

    bulk = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": [theirs["id"]], "action": "approve"},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["affected"] == 0
