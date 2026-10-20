"""Dashboard tests: the metrics and the activity feed reflect the real rows."""

from __future__ import annotations

from tests.conftest import API


def test_metrics_reflect_the_created_rows(authenticated_client) -> None:
    first_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Campaign One", "target_website": "https://one.example"},
    ).json()
    _second_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Campaign Two", "target_website": "https://two.example"},
    ).json()

    opportunity_ids = []
    for index in range(3):
        response = authenticated_client.post(
            f"{API}/opportunities",
            json={
                "name": f"Directory {index}",
                "opportunity_url": f"https://directory{index}.example.org/add",
                "category": "BUSINESS_DIRECTORY",
                "project_id": first_project["id"],
            },
        )
        assert response.status_code == 201, response.text
        opportunity_ids.append(response.json()["id"])

    approved = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": opportunity_ids[:1], "action": "approve"},
    )
    assert approved.json()["affected"] == 1

    queued = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_ids[1]], "type": "SUBMIT"}
    )
    assert queued.json()["created"] == 1

    metrics = authenticated_client.get(f"{API}/dashboard/metrics")
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()

    assert body["projects"] == 2
    assert body["opportunities"] == 3
    assert body["approved"] == 1
    assert body["queued"] == 1
    assert body["running"] == 0
    assert body["failed"] == 0
    assert body["awaiting_retry"] == 0
    assert body["pending_manual"] == 0
    assert body["published"] == 0
    assert body["verified_live"] == 0
    assert body["by_status"] == {"QUEUED": 1}
    assert body["by_category"] == [{"category": "BUSINESS_DIRECTORY", "count": 3}]
    assert body["generated_at"]


def test_metrics_can_be_scoped_to_a_project(authenticated_client) -> None:
    project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Scoped Campaign", "target_website": "https://scoped.example"},
    ).json()
    other = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Other Campaign", "target_website": "https://other.example"},
    ).json()

    for project_id in (project["id"], other["id"]):
        response = authenticated_client.post(
            f"{API}/opportunities",
            json={
                "name": "Directory",
                "opportunity_url": f"https://{project_id[:6]}.example.org/add",
                "project_id": project_id,
            },
        )
        assert response.status_code == 201, response.text

    metrics = authenticated_client.get(
        f"{API}/dashboard/metrics", params={"project_id": project["id"]}
    ).json()

    assert metrics["projects"] == 1
    assert metrics["opportunities"] == 1


def test_activity_returns_the_emitted_events(authenticated_client, project_id) -> None:
    authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Directory Example",
            "opportunity_url": "https://directory.example.org/add-your-business",
            "project_id": project_id,
        },
    )

    activity = authenticated_client.get(f"{API}/activity")
    assert activity.status_code == 200, activity.text
    body = activity.json()
    assert body["total"] >= 1

    event_types = [item["event_type"] for item in body["items"]]
    assert "website.added" in event_types

    added = next(item for item in body["items"] if item["event_type"] == "website.added")
    assert added["project_id"] == project_id
    assert added["level"] == "INFO"
    assert added["metadata"]["url"].startswith("https://directory.example.org")
    assert added["created_at"]


def test_activity_can_be_filtered_by_event_type(authenticated_client, project_id) -> None:
    authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Directory Example",
            "opportunity_url": "https://directory.example.org/add-your-business",
            "project_id": project_id,
        },
    )

    filtered = authenticated_client.get(
        f"{API}/activity", params={"event_type": "website.added"}
    ).json()

    assert filtered["total"] >= 1
    assert {item["event_type"] for item in filtered["items"]} == {"website.added"}


def test_recent_events_endpoint_lists_the_events(authenticated_client, project_id) -> None:
    authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Directory Example",
            "opportunity_url": "https://directory.example.org/add-your-business",
            "project_id": project_id,
        },
    )

    response = authenticated_client.get(f"{API}/events/recent")
    assert response.status_code == 200, response.text
    events = response.json()
    assert any(event["event_type"] == "website.added" for event in events)
