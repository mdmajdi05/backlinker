"""The campaign cockpit: add websites, start the work, watch the rows.

The cockpit is a view over websites, opportunities, tasks and backlink
records.  These tests pin the promises of that view:

* every pasted URL is answered (added, linked, existing or invalid),
* one click fills the details from the profile and queues the ready rows,
* a row without complete details is reported instead of sent half filled,
* a submission the operator made by hand can be recorded and verified.
"""

from __future__ import annotations

from app.db.models import BacklinkRecord, Opportunity, Task

API = "/api/v1"


def _profile(client, **overrides) -> dict:
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


def _project(client, profile_id: str | None = None, **extra) -> dict:
    body = {"name": "Campaign project", "target_website": "https://acme.example/blog"}
    if profile_id:
        body["business_profile_id"] = profile_id
    body.update(extra)
    response = client.post(f"{API}/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _add(client, project_id: str, text: str) -> dict:
    response = client.post(
        f"{API}/projects/{project_id}/campaign/websites", json={"text": text}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_input_box_answers_every_url(authenticated_client) -> None:
    project = _project(authenticated_client)

    result = _add(
        authenticated_client,
        project["id"],
        "https://first.example/add, second.example/submit\nnot-a-domain\n"
        "https://first.example/add",
    )

    statuses = [row["status"] for row in result["results"]]
    assert statuses == ["added", "added", "invalid"], result
    assert result["added"] == 2
    assert result["invalid"] == 1
    assert result["results"][2]["message"]

    # Both sites are in the central list *and* in the project.
    websites = authenticated_client.get(f"{API}/websites", params={"page_size": 50})
    assert websites.status_code == 200, websites.text
    assert {row["domain"] for row in websites.json()["items"]} == {
        "first.example",
        "second.example",
    }

    campaign = authenticated_client.get(f"{API}/projects/{project['id']}/campaign")
    assert campaign.status_code == 200, campaign.text
    body = campaign.json()
    assert body["summary"]["total"] == 2
    assert {row["status"] for row in body["rows"]} == {"NEEDS_DETAILS"}
    assert all(row["details_percent"] < 100 for row in body["rows"])

    # Adding the same URL to another project links the existing website.
    other = _project(authenticated_client, name="Other project")
    linked = _add(authenticated_client, other["id"], "https://first.example/add")
    assert linked["results"][0]["status"] == "linked"
    assert linked["linked"] == 1


def test_start_fills_details_and_queues_the_ready_rows(
    authenticated_client, db_session
) -> None:
    profile = _profile(authenticated_client)
    project = _project(authenticated_client, profile_id=profile["id"])
    _add(authenticated_client, project["id"], "https://one.example/add, two.example/add")

    # Before the first Start the values are not written yet, but the profile
    # can supply them - so the rows are ready, not blocked.
    before = authenticated_client.get(
        f"{API}/projects/{project['id']}/campaign"
    ).json()
    assert {row["status"] for row in before["rows"]} == {"READY"}
    assert all(row["details_percent"] == 100 for row in before["rows"])
    assert all(row["missing"] == [] for row in before["rows"])
    assert before["summary"]["needs_details"] == 0

    started = authenticated_client.post(
        f"{API}/projects/{project['id']}/campaign/start"
    )
    assert started.status_code == 200, started.text
    result = started.json()
    assert result["queued"] == 2, result
    assert result["needs_details"] == []

    db_session.rollback()
    tasks = db_session.query(Task).filter_by(project_id=project["id"], type="SUBMIT").all()
    assert len(tasks) == 2
    assert {task.status for task in tasks} == {"QUEUED"}
    assert all(task.execution_environment == "LOCAL" for task in tasks)

    # Pressing start again does not duplicate the work.
    again = authenticated_client.post(
        f"{API}/projects/{project['id']}/campaign/start"
    )
    assert again.status_code == 200, again.text
    assert again.json()["queued"] == 0
    assert again.json()["already_queued"] == 2

    campaign = authenticated_client.get(f"{API}/projects/{project['id']}/campaign").json()
    assert campaign["summary"]["in_progress"] == 2
    assert campaign["summary"]["percent"] == 0
    assert {row["status"] for row in campaign["rows"]} == {"QUEUED"}


def test_a_row_without_details_is_reported_instead_of_queued(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    _add(authenticated_client, project["id"], "https://needs.example/add")

    started = authenticated_client.post(f"{API}/projects/{project['id']}/campaign/start")
    assert started.status_code == 200, started.text
    result = started.json()
    assert result["queued"] == 0
    assert len(result["needs_details"]) == 1
    assert result["needs_details"][0]["missing"], "the missing fields are named"

    db_session.rollback()
    assert db_session.query(Task).filter_by(project_id=project["id"]).count() == 0


def test_a_manual_submission_can_be_recorded_and_verified(
    authenticated_client, db_session
) -> None:
    profile = _profile(authenticated_client)
    project = _project(authenticated_client, profile_id=profile["id"])
    _add(authenticated_client, project["id"], "https://manual.example/add")
    authenticated_client.post(f"{API}/projects/{project['id']}/campaign/start")
    opportunity = (
        db_session.query(Opportunity).filter_by(project_id=project["id"]).one()
    )
    opportunity_id = opportunity.id

    submitted = authenticated_client.post(
        f"{API}/projects/{project['id']}/campaign/{opportunity_id}/submit",
        json={"published_url": "https://manual.example/acme", "anchor_text": "Acme"},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["verification_status"] == "SUBMITTED"
    assert body["backlink_id"]

    db_session.rollback()
    record = db_session.get(BacklinkRecord, body["backlink_id"])
    assert record is not None
    assert record.published_page_url == "https://manual.example/acme"
    assert record.observed_anchor_text == "Acme"
    task = (
        db_session.query(Task)
        .filter_by(opportunity_id=opportunity_id, type="SUBMIT")
        .one()
    )
    assert task.status == "SUBMITTED"
    verify = db_session.query(Task).filter_by(opportunity_id=opportunity_id, type="VERIFY")
    assert verify.count() == 1

    campaign = authenticated_client.get(f"{API}/projects/{project['id']}/campaign").json()
    assert campaign["rows"][0]["status"] == "SUBMITTED"
    assert campaign["rows"][0]["verification_status"] == "SUBMITTED"
    assert campaign["summary"]["done"] == 1
    assert campaign["summary"]["remaining"] == 0
    assert campaign["summary"]["percent"] == 100

    # Pressing start again never queues a finished submission twice.
    again = authenticated_client.post(
        f"{API}/projects/{project['id']}/campaign/start"
    )
    assert again.status_code == 200, again.text
    assert again.json()["queued"] == 0
    db_session.rollback()
    assert (
        db_session.query(Task)
        .filter_by(opportunity_id=opportunity_id, type="SUBMIT")
        .count()
        == 1
    )


def test_a_spreadsheet_import_links_the_rows_to_the_project(
    authenticated_client, db_session
) -> None:
    project = _project(authenticated_client)
    csv = (
        "Website,Opportunity URL,Category,Description\n"
        "Import One,https://import-one.example/add,BUSINESS_DIRECTORY,First site\n"
        "Import Two,https://import-two.example/add,BUSINESS_DIRECTORY,Second site\n"
    )
    response = authenticated_client.post(
        f"{API}/projects/{project['id']}/campaign/import",
        files={"file": ("campaign.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 2
    assert result["linked"] == 2

    linked = (
        db_session.query(Opportunity).filter_by(project_id=project["id"]).count()
    )
    assert linked == 2
