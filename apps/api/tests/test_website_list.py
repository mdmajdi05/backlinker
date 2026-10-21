"""Tests of the central website list.

The list is the one place where the sites the backlinks are made at live.  It
is independent of the projects: a website is added by hand or imported from a
spreadsheet, it can be marked as "not working" or removed, and a project picks
the sites it wants from it.
"""

from __future__ import annotations

import io

from app.db.models import Opportunity, Task, Website
from tests.conftest import API


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _add_website(client, **overrides) -> dict:
    """Add a website to the central list and return the row."""
    payload = {
        "opportunity_url": "https://directory.example.org/add-your-business",
        "name": "Example Directory",
        "category": "BUSINESS_DIRECTORY",
        "niche": "pets",
    }
    payload.update(overrides)
    response = client.post(f"{API}/websites", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _build_workbook(rows: list[list[str]], headers: list[str] | None = None) -> bytes:
    """Build an xlsx workbook with the columns of the campaign import."""
    from openpyxl import Workbook

    columns = headers or [
        "Website",
        "Opportunity URL",
        "Category",
        "Anchor Text",
        "Target URL",
        "Description",
        "Email",
        "Notes",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Websites"
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _import(client, rows: list[list[str]], **fields) -> dict:
    """Import a workbook into the central list."""
    payload = _build_workbook(rows)
    response = client.post(
        f"{API}/websites/import",
        files={
            "file": (
                "websites.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={key: value for key, value in fields.items() if value},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_profile(client, **overrides) -> dict:
    payload = {
        "name": "Acme Analytics",
        "primary_website": "https://acme.example",
        "description": "Acme builds analytics tools for small teams.",
        "contact_email": "hello@acme.example",
        "contact_phone": "+1 555 0100",
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
# The list itself
# --------------------------------------------------------------------------
def test_a_website_can_be_added_without_a_project(authenticated_client) -> None:
    """The central list lives on its own - no project is needed."""
    row = _add_website(authenticated_client)

    assert row["name"] == "Example Directory"
    assert row["domain"] == "directory.example.org"
    assert row["opportunity_url"] == "https://directory.example.org/add-your-business"
    assert row["category"] == "BUSINESS_DIRECTORY"
    assert row["niche"] == "pets"
    assert row["status"] == "ACTIVE"
    assert row["project_ids"] == []
    assert row["project_count"] == 0
    assert row["stats"]["opportunities"] == 0
    assert row["created_at"]
    assert row["updated_at"]


def test_the_same_website_is_not_added_twice(authenticated_client) -> None:
    _add_website(authenticated_client)

    response = authenticated_client.post(
        f"{API}/websites",
        json={"opportunity_url": "https://directory.example.org/add-your-business"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "duplicate"


def test_the_list_can_be_filtered(authenticated_client) -> None:
    _add_website(
        authenticated_client,
        opportunity_url="https://pets.example.org/submit",
        name="Pets Directory",
        category="BUSINESS_DIRECTORY",
        niche="pets",
    )
    _add_website(
        authenticated_client,
        opportunity_url="https://saas.example.org/submit",
        name="SaaS Directory",
        category="INDUSTRY_DIRECTORY",
        niche="software",
    )
    _add_website(
        authenticated_client,
        opportunity_url="https://blog.example.org/submit",
        name="Blog Network",
        category="BLOG_NETWORK",
        niche="pets",
    )

    everything = authenticated_client.get(f"{API}/websites")
    assert everything.status_code == 200, everything.text
    assert everything.json()["total"] == 3

    by_category = authenticated_client.get(f"{API}/websites?category=BUSINESS_DIRECTORY")
    assert by_category.status_code == 200, by_category.text
    assert by_category.json()["total"] == 1
    assert by_category.json()["items"][0]["name"] == "Pets Directory"

    by_niche = authenticated_client.get(f"{API}/websites?niche=pets")
    assert by_niche.status_code == 200, by_niche.text
    assert by_niche.json()["total"] == 2

    by_status = authenticated_client.get(f"{API}/websites?status=ACTIVE")
    assert by_status.status_code == 200, by_status.text
    assert by_status.json()["total"] == 3

    by_search = authenticated_client.get(f"{API}/websites?search=saas")
    assert by_search.status_code == 200, by_search.text
    assert by_search.json()["total"] == 1
    assert by_search.json()["items"][0]["domain"] == "saas.example.org"

    empty = authenticated_client.get(f"{API}/websites?category=UNKNOWN_CATEGORY")
    assert empty.status_code == 200, empty.text
    assert empty.json()["total"] == 0


def test_the_list_is_paginated_and_sorted(authenticated_client) -> None:
    for index in range(5):
        _add_website(
            authenticated_client,
            opportunity_url=f"https://site{index}.example.org/submit",
            name=f"Site {index}",
        )

    page = authenticated_client.get(f"{API}/websites?page=2&page_size=2&sort=name&order=asc")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["pages"] == 3
    assert [item["name"] for item in body["items"]] == ["Site 2", "Site 3"]


# --------------------------------------------------------------------------
# Status and removal
# --------------------------------------------------------------------------
def test_the_status_of_a_website_can_be_changed(authenticated_client) -> None:
    row = _add_website(authenticated_client)

    response = authenticated_client.patch(
        f"{API}/websites/{row['id']}", json={"status": "NOT_WORKING"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "NOT_WORKING"

    listed = authenticated_client.get(f"{API}/websites?status=NOT_WORKING")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1


def test_an_unknown_status_is_rejected(authenticated_client) -> None:
    row = _add_website(authenticated_client)

    response = authenticated_client.patch(
        f"{API}/websites/{row['id']}", json={"status": "WHATEVER"}
    )

    assert response.status_code == 422, response.text


def test_a_removed_website_leaves_the_list_but_keeps_the_history(
    authenticated_client, project_id, db_session
) -> None:
    """The removal is soft - the opportunities and the tasks stay."""
    row = _add_website(authenticated_client)
    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Example Directory",
            "opportunity_url": row["opportunity_url"],
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    )
    assert opportunity.status_code == 201, opportunity.text
    opportunity_id = opportunity.json()["id"]

    removed = authenticated_client.delete(f"{API}/websites/{row['id']}")
    assert removed.status_code == 204, removed.text

    # The website is gone from the list ...
    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 0

    # ... but the row is still there and it is marked as deleted.
    db_session.rollback()
    website = db_session.get(Website, row["id"])
    assert website is not None
    assert website.status == "DELETED"
    assert db_session.query(Opportunity).filter_by(id=opportunity_id).count() == 1

    # The deleted row can still be asked for.
    deleted = authenticated_client.get(f"{API}/websites?status=DELETED")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["total"] == 1
    assert deleted.json()["items"][0]["id"] == row["id"]


def test_the_task_history_survives_the_removal(
    authenticated_client, project_id, db_session
) -> None:
    row = _add_website(authenticated_client)
    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Example Directory",
            "opportunity_url": row["opportunity_url"],
            "project_id": project_id,
        },
    )
    assert opportunity.status_code == 201, opportunity.text
    opportunity_id = opportunity.json()["id"]
    db_session.rollback()
    db_session.add(
        Task(
            project_id=project_id,
            opportunity_id=opportunity_id,
            website_id=row["id"],
            type="SUBMIT",
            status="SUBMITTED",
            idempotency_key="history-task",
        )
    )
    db_session.commit()

    removed = authenticated_client.delete(f"{API}/websites/{row['id']}")
    assert removed.status_code == 204, removed.text

    db_session.rollback()
    assert db_session.query(Task).filter_by(idempotency_key="history-task").count() == 1
    assert db_session.query(Opportunity).filter_by(id=opportunity_id).count() == 1


# --------------------------------------------------------------------------
# The import
# --------------------------------------------------------------------------
def test_a_spreadsheet_can_be_imported_into_the_list(authenticated_client) -> None:
    _add_website(
        authenticated_client,
        opportunity_url="https://known.example.org/submit",
        name="Known Directory",
        niche="pets",
    )

    result = _import(
        authenticated_client,
        [
            [
                "New Directory",
                "https://new.example.org/submit",
                "BUSINESS_DIRECTORY",
                "Acme Analytics",
                "https://acme.example",
                "A description",
                "hello@acme.example",
                "A note",
            ],
            [
                "Known Directory",
                "https://known.example.org/submit",
                "INDUSTRY_DIRECTORY",
                "Acme Analytics",
                "https://acme.example",
                "",
                "",
                "Another note",
            ],
            [
                "Broken Directory",
                "not a url",
                "BUSINESS_DIRECTORY",
                "",
                "",
                "",
                "",
                "",
            ],
        ],
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert result["invalid"] == 1

    actions = {row["row"]: row["action"] for row in result["rows"]}
    assert actions[2] == "created"
    assert actions[3] == "updated"
    assert actions[4] == "invalid"

    invalid = next(row for row in result["rows"] if row["action"] == "invalid")
    assert invalid["reason"]
    assert "space" in invalid["reason"] or "scheme" in invalid["reason"]

    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 2
    names = {item["name"] for item in listed.json()["items"]}
    assert names == {"Known Directory", "New Directory"}


def test_the_import_uses_the_defaults_of_the_form(authenticated_client) -> None:
    result = _import(
        authenticated_client,
        [["Imported Directory", "https://imported.example.org/submit", "", "", "", "", "", ""]],
        category="INDUSTRY_DIRECTORY",
        niche="software",
        status="NEEDS_REVIEW",
    )

    assert result["created"] == 1
    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    row = listed.json()["items"][0]
    assert row["category"] == "INDUSTRY_DIRECTORY"
    assert row["niche"] == "software"
    assert row["status"] == "NEEDS_REVIEW"


def test_the_import_refreshes_an_existing_website(authenticated_client) -> None:
    _add_website(
        authenticated_client,
        opportunity_url="https://known.example.org/submit",
        name="Old Name",
        category="BUSINESS_DIRECTORY",
    )

    result = _import(
        authenticated_client,
        [
            [
                "New Name",
                "https://known.example.org/submit",
                "INDUSTRY_DIRECTORY",
                "",
                "",
                "",
                "",
                "A fresh note",
            ]
        ],
    )

    assert result["updated"] == 1
    assert result["created"] == 0
    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    row = listed.json()["items"][0]
    assert row["name"] == "New Name"
    assert row["category"] == "INDUSTRY_DIRECTORY"
    assert row["notes"] == "A fresh note"


def test_a_removed_website_is_not_resurrected_by_an_import(authenticated_client) -> None:
    row = _add_website(
        authenticated_client, opportunity_url="https://gone.example.org/submit"
    )
    removed = authenticated_client.delete(f"{API}/websites/{row['id']}")
    assert removed.status_code == 204, removed.text

    result = _import(
        authenticated_client,
        [["Gone Directory", "https://gone.example.org/submit", "", "", "", "", "", ""]],
    )

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert result["rows"][0]["action"] == "skipped"
    assert result["rows"][0]["reason"]


def test_the_website_column_may_carry_the_url(authenticated_client) -> None:
    result = _import(
        authenticated_client,
        [["https://only-url.example.org/submit", "", "", "", "", "", "", ""]],
    )

    assert result["created"] == 1
    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    row = listed.json()["items"][0]
    assert row["opportunity_url"] == "https://only-url.example.org/submit"
    assert row["name"] == "only-url.example.org"


def test_a_file_without_a_known_column_is_refused(authenticated_client) -> None:
    payload = _build_workbook([["a", "b", "c"]], headers=["First", "Second", "Third"])
    response = authenticated_client.post(
        f"{API}/websites/import",
        files={"file": ("websites.xlsx", payload, "application/octet-stream")},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "import_failed"


def test_an_unknown_import_status_is_refused(authenticated_client) -> None:
    payload = _build_workbook(
        [["A Directory", "https://status.example.org/submit", "", "", "", "", "", ""]]
    )
    response = authenticated_client.post(
        f"{API}/websites/import",
        files={"file": ("websites.xlsx", payload, "application/octet-stream")},
        data={"status": "WHATEVER"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_status"


# --------------------------------------------------------------------------
# Choosing websites for a project
# --------------------------------------------------------------------------
def test_websites_can_be_chosen_for_a_project(
    authenticated_client, project_id, db_session
) -> None:
    first = _add_website(
        authenticated_client,
        opportunity_url="https://one.example.org/submit",
        name="One",
        category="BUSINESS_DIRECTORY",
        niche="pets",
    )
    second = _add_website(
        authenticated_client,
        opportunity_url="https://two.example.org/submit",
        name="Two",
        category="INDUSTRY_DIRECTORY",
        niche="pets",
    )

    response = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={
            "website_ids": [first["id"], second["id"]],
            "anchor_text": "Acme Analytics",
            "target_landing_page": "https://acme.example/landing",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["linked"] == 2
    assert body["skipped"] == 0
    assert body["tasks_created"] == 2
    assert len(body["task_ids"]) == 2

    db_session.rollback()
    opportunities = db_session.query(Opportunity).filter_by(project_id=project_id).all()
    assert len(opportunities) == 2
    landing = {item.target_landing_page for item in opportunities}
    assert landing == {"https://acme.example/landing"}


def test_choosing_twice_does_not_duplicate_the_work(
    authenticated_client, project_id, db_session
) -> None:
    row = _add_website(authenticated_client)

    first = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={"website_ids": [row["id"]]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["linked"] == 1

    second = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={"website_ids": [row["id"]]},
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["linked"] == 0
    assert body["skipped"] == 1
    assert body["tasks_created"] == 0
    assert body["task_ids"] == []

    db_session.rollback()
    assert db_session.query(Opportunity).filter_by(project_id=project_id).count() == 1
    assert db_session.query(Task).filter_by(website_id=row["id"]).count() == 1


def test_the_filtered_out_websites_are_skipped(authenticated_client, project_id) -> None:
    wanted = _add_website(
        authenticated_client,
        opportunity_url="https://wanted.example.org/submit",
        category="BUSINESS_DIRECTORY",
        niche="pets",
    )
    other_category = _add_website(
        authenticated_client,
        opportunity_url="https://other-category.example.org/submit",
        category="INDUSTRY_DIRECTORY",
        niche="pets",
    )
    other_niche = _add_website(
        authenticated_client,
        opportunity_url="https://other-niche.example.org/submit",
        category="BUSINESS_DIRECTORY",
        niche="software",
    )

    response = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={
            "website_ids": [wanted["id"], other_category["id"], other_niche["id"]],
            "category": "BUSINESS_DIRECTORY",
            "niche": "pets",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["linked"] == 1
    assert body["skipped"] == 2
    assert body["tasks_created"] == 1


def test_a_removed_website_is_not_chosen(authenticated_client, project_id) -> None:
    row = _add_website(authenticated_client)
    removed = authenticated_client.delete(f"{API}/websites/{row['id']}")
    assert removed.status_code == 204, removed.text

    response = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={"website_ids": [row["id"]]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["linked"] == 0
    assert response.json()["skipped"] == 1


# --------------------------------------------------------------------------
# The statistics
# --------------------------------------------------------------------------
def test_the_statistics_count_the_tasks_of_a_website(
    authenticated_client, project_id, db_session
) -> None:
    row = _add_website(authenticated_client)
    chosen = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={"website_ids": [row["id"]]},
    )
    assert chosen.status_code == 200, chosen.text
    opportunity_id = db_session.query(Opportunity).filter_by(
        website_id=row["id"]
    ).first().id

    db_session.rollback()
    for index, status in enumerate(
        ["SUBMITTED", "VERIFIED_LIVE", "FAILED", "WAITING_FOR_USER", "RUNNING"]
    ):
        db_session.add(
            Task(
                project_id=project_id,
                opportunity_id=opportunity_id,
                website_id=row["id"],
                type="SUBMIT",
                status=status,
                idempotency_key=f"stats-task-{index}",
            )
        )
    db_session.commit()

    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    stats = listed.json()["items"][0]["stats"]
    assert stats["opportunities"] == 1
    assert stats["submitted"] == 2  # SUBMITTED + VERIFIED_LIVE
    assert stats["verified"] == 1
    assert stats["failed"] == 1
    assert stats["pending"] == 2  # the queued task of the choice + RUNNING
    assert stats["waiting_for_details"] == 1
    assert stats["last_attempt_at"]

    rows = authenticated_client.get(f"{API}/websites/stats?project_id={project_id}")
    assert rows.status_code == 200, rows.text
    body = rows.json()
    assert len(body) == 1
    assert body[0]["domain"] == row["domain"]
    assert body[0]["name"] == row["name"]
    assert body[0]["category"] == row["category"]
    assert body[0]["status"] == row["status"]
    assert body[0]["submitted"] == 2
    assert body[0]["verified"] == 1
    assert body[0]["failed"] == 1
    assert body[0]["pending"] == 2
    assert body[0]["waiting_for_details"] == 1


def test_the_list_shows_the_projects_a_website_is_used_in(
    authenticated_client, project_id
) -> None:
    row = _add_website(authenticated_client)
    chosen = authenticated_client.post(
        f"{API}/projects/{project_id}/websites/choose",
        json={"website_ids": [row["id"]]},
    )
    assert chosen.status_code == 200, chosen.text

    listed = authenticated_client.get(f"{API}/websites")
    assert listed.status_code == 200, listed.text
    item = listed.json()["items"][0]
    assert item["project_ids"] == [project_id]
    assert item["project_count"] == 1

    filtered = authenticated_client.get(f"{API}/websites?project_id={project_id}")
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1


# --------------------------------------------------------------------------
# The gap report
# --------------------------------------------------------------------------
def test_the_gap_report_lists_the_missing_details(
    authenticated_client, project_id, opportunity_id
) -> None:
    response = authenticated_client.get(
        f"{API}/opportunities/{opportunity_id}/details/gaps"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {"name", "website", "description"} <= set(body["required"])
    assert {"name", "website", "description"} <= set(body["missing"])
    assert body["filled"] == []
    assert body["source"] == "none"
    # Without a business profile nothing can be derived.
    assert body["derivable"] == []
    reasons = {item["field"]: item["reason"] for item in body["not_derivable"]}
    assert "business profile" in reasons["name"]
    assert all(item["label"] for item in body["not_derivable"])


def test_the_gap_report_separates_the_derivable_details(
    authenticated_client, project_id, opportunity_id
) -> None:
    profile = _create_profile(authenticated_client)
    _attach_profile(authenticated_client, project_id, profile["id"])

    response = authenticated_client.get(
        f"{API}/opportunities/{opportunity_id}/details/gaps"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "profile"
    assert {"name", "website", "description"} <= set(body["derivable"])
    assert body["not_derivable"] == []


def test_the_gap_report_names_the_details_that_cannot_be_derived(
    authenticated_client, project_id
) -> None:
    """A field the business profile has no value for is reported with a reason."""
    profile = _create_profile(authenticated_client, contact_phone=None)
    _attach_profile(authenticated_client, project_id, profile["id"])

    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Local Citation",
            "opportunity_url": "https://local.example.org/submit",
            "category": "LOCAL_CITATION",
            "project_id": project_id,
        },
    )
    assert opportunity.status_code == 201, opportunity.text

    response = authenticated_client.get(
        f"{API}/opportunities/{opportunity.json()['id']}/details/gaps"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "address_region" in body["missing"]
    assert "address_region" not in body["derivable"]
    reasons = {item["field"]: item for item in body["not_derivable"]}
    assert "address_region" in reasons
    assert reasons["address_region"]["label"]
    assert "business profile" in reasons["address_region"]["reason"]


def test_the_gap_report_of_a_foreign_opportunity_is_not_readable(
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
            "opportunity_url": "https://foreign.example.org/submit",
            "project_id": their_project.json()["id"],
        },
        headers=other_auth_headers,
    )
    assert theirs.status_code == 201, theirs.text

    response = authenticated_client.get(
        f"{API}/opportunities/{theirs.json()['id']}/details/gaps"
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"
