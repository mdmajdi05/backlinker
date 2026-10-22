"""One truth for the status of a project and for the details of a profile."""

from __future__ import annotations

from app.db.models import Opportunity, Project, Task
from app.services import autopilot

API = "/api/v1"


def _project(client, **extra) -> dict:
    body = {"name": "Truth project", "target_website": "https://truth.example"}
    body.update(extra)
    response = client.post(f"{API}/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _opportunity(client, project_id: str, domain: str) -> dict:
    website = client.post(
        f"{API}/websites",
        json={"opportunity_url": f"https://{domain}/add", "name": "Truth site"},
    )
    assert website.status_code == 201, website.text
    created = client.post(
        f"{API}/opportunities",
        json={
            "opportunity_url": website.json()["opportunity_url"],
            "name": "Truth site",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_a_paused_project_gets_no_new_tasks_from_the_auto_pilot(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    opportunity = _opportunity(authenticated_client, project["id"], "paused-autopilot.example")

    state = authenticated_client.post(
        f"{API}/projects/{project['id']}/autopilot", json={"enabled": True}
    )
    assert state.status_code == 200, state.text

    # Pausing the project is the one switch that stops the work.
    paused = authenticated_client.patch(
        f"{API}/projects/{project['id']}", json={"status": "PAUSED"}
    )
    assert paused.status_code == 200, paused.text

    approved = authenticated_client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": [opportunity["id"]], "action": "approve"},
    )
    assert approved.status_code == 200, approved.text
    db_session.rollback()
    assert autopilot.queue_approved(db_session, project["id"]) == []
    assert (
        db_session.query(Task).filter_by(opportunity_id=opportunity["id"]).count() == 0
    )

    # Resuming it starts the work again - nothing was lost.
    resumed = authenticated_client.patch(
        f"{API}/projects/{project['id']}", json={"status": "ACTIVE"}
    )
    assert resumed.status_code == 200, resumed.text
    db_session.rollback()
    tasks = autopilot.queue_approved(db_session, project["id"])
    assert tasks, "a resumed project should queue its approved opportunities"


def test_changing_the_profile_refreshes_the_stored_details(
    authenticated_client, db_session
) -> None:
    project = _project(
        authenticated_client,
        details={
            "company_name": "Truth Ltd",
            "email": "old@truth.example",
            "phone": "+1 555 0100",
            "website": "https://truth.example",
        },
    )
    opportunity = _opportunity(authenticated_client, project["id"], "refresh-details.example")

    generated = authenticated_client.post(
        f"{API}/opportunities/{opportunity['id']}/details/generate"
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["details"]["email"] == "old@truth.example"

    # The profile is the one truth - the copy of the opportunity follows it.
    profile_id = authenticated_client.get(
        f"{API}/projects/{project['id']}/backlink-details"
    ).json()["profile_id"]
    profile = authenticated_client.get(f"{API}/profiles/{profile_id}").json()
    updated = {**profile, "contact_email": "new@truth.example"}
    for key in ("id", "created_at", "updated_at"):
        updated.pop(key, None)
    saved = authenticated_client.put(f"{API}/profiles/{profile_id}", json=updated)
    assert saved.status_code == 200, saved.text

    details = authenticated_client.get(f"{API}/opportunities/{opportunity['id']}/details")
    assert details.status_code == 200, details.text
    assert details.json()["email"] == "new@truth.example"

    db_session.rollback()
    assert db_session.get(Opportunity, opportunity["id"]) is not None
    assert db_session.get(Project, project["id"]).status == "ACTIVE"


def test_a_value_typed_for_one_website_is_not_overwritten(authenticated_client) -> None:
    project = _project(
        authenticated_client,
        details={
            "company_name": "Manual Ltd",
            "email": "profile@manual.example",
            "website": "https://manual.example",
        },
    )
    opportunity = _opportunity(authenticated_client, project["id"], "manual-override.example")

    generated = authenticated_client.post(
        f"{API}/opportunities/{opportunity['id']}/details/generate"
    )
    assert generated.status_code == 200, generated.text

    # The operator edits the e-mail for this one website only.
    current = authenticated_client.get(f"{API}/opportunities/{opportunity['id']}/details").json()
    manual = {**current, "email": "special@manual.example"}
    for key in ("id", "opportunity_id", "project_id", "website_id", "created_at", "updated_at"):
        manual.pop(key, None)
    changed = authenticated_client.put(
        f"{API}/opportunities/{opportunity['id']}/details", json=manual
    )
    assert changed.status_code == 200, changed.text

    profile_id = authenticated_client.get(
        f"{API}/projects/{project['id']}/backlink-details"
    ).json()["profile_id"]
    profile = authenticated_client.get(f"{API}/profiles/{profile_id}").json()
    updated = {**profile, "contact_email": "profile2@manual.example"}
    for key in ("id", "created_at", "updated_at"):
        updated.pop(key, None)
    assert authenticated_client.put(f"{API}/profiles/{profile_id}", json=updated).status_code == 200

    details = authenticated_client.get(f"{API}/opportunities/{opportunity['id']}/details").json()
    assert details["email"] == "special@manual.example"
