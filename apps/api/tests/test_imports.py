"""Import tests: spreadsheet preview and commit (skipped without the importer)."""

from __future__ import annotations

import io

import pytest

from app.db.models import Opportunity, Website
from tests.conftest import API

pytest.importorskip(
    "app.services.dataflow.importer",
    reason="the spreadsheet import engine (app.services.dataflow.importer) is not available yet",
    exc_type=ImportError,
)

# Public IP literals are used on purpose: they are resolved without a DNS
# lookup, so the test stays completely offline.
NEW_URL = "https://93.184.216.34/directory-new"
KNOWN_URL = "https://93.184.216.35/directory-known"
CONFLICT_URL = "https://93.184.216.36/directory-conflict"
INVALID_URL = "https://93.184.216.37/directory-invalid"

HEADERS = [
    "Project",
    "Website",
    "Target URL",
    "Backlink Website",
    "Status",
    "Anchor Text",
    "Category",
]


def _build_workbook(rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Opportunities"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _preview(client, project_id: str, project_name: str, rows: list[list[str]]) -> dict:
    payload = _build_workbook(rows)
    response = client.post(
        f"{API}/imports/preview",
        files={
            "file": (
                "opportunities.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"project_id": project_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_reports_the_action_of_every_row(authenticated_client, project_id) -> None:
    project_name = authenticated_client.get(f"{API}/projects/{project_id}").json()["name"]
    # An opportunity that already exists -> the row becomes an UPDATE.
    existing = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Known Directory",
            "opportunity_url": KNOWN_URL,
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    )
    assert existing.status_code == 201, existing.text

    rows = [
        [project_name, "New Directory", "https://target.example/", NEW_URL, "PENDING", "Acme", ""],
        [project_name, "Known Directory", "https://target.example/", KNOWN_URL, "PENDING", "Acme", ""],
        [
            project_name,
            "Conflicting Directory",
            "https://target.example/",
            CONFLICT_URL,
            "VERIFIED_LIVE",
            "Acme",
            "",
        ],
        [project_name, "Invalid Directory", "", INVALID_URL, "PENDING", "Acme", ""],
    ]

    preview = _preview(authenticated_client, project_id, project_name, rows)

    assert preview["file_name"] == "opportunities.xlsx"
    assert preview["sheets"] == ["Opportunities"]
    assert preview["counts"]["total"] == 4

    actions = {row["row_number"]: row["action"] for row in preview["rows"]}
    assert actions[2] == "CREATE"
    assert actions[3] == "UPDATE"
    assert actions[4] == "CONFLICT"
    assert actions[5] == "INVALID"

    assert preview["counts"]["create"] == 1
    assert preview["counts"]["update"] == 1
    assert preview["counts"]["conflict"] == 1
    assert preview["counts"]["invalid"] == 1

    mapped = {entry["source_column"]: entry["target_field"] for entry in preview["detected_mapping"]}
    assert mapped["Backlink Website"] == "opportunity_url"
    assert mapped["Target URL"] == "target_url"


def test_commit_applies_the_planned_actions(
    authenticated_client, project_id, db_session
) -> None:
    project_name = authenticated_client.get(f"{API}/projects/{project_id}").json()["name"]
    rows = [
        [project_name, "New Directory", "https://target.example/", NEW_URL, "PENDING", "Acme", ""],
    ]

    preview = _preview(authenticated_client, project_id, project_name, rows)
    assert preview["counts"]["create"] == 1

    commit = authenticated_client.post(
        f"{API}/imports/{preview['import_job_id']}/commit",
        json={"apply_actions": ["CREATE"], "dry_run": False},
    )

    assert commit.status_code == 200, commit.text
    body = commit.json()
    assert body["status"] == "COMMITTED"
    assert body["created_count"] == 1
    assert body["total_rows"] == 1
    assert body["committed_at"] is not None

    db_session.rollback()
    websites = db_session.query(Website).all()
    assert len(websites) == 1
    assert websites[0].opportunity_url == NEW_URL
    assert db_session.query(Opportunity).filter_by(project_id=project_id).count() == 1


def test_the_import_rows_are_persisted(authenticated_client, project_id) -> None:
    project_name = authenticated_client.get(f"{API}/projects/{project_id}").json()["name"]
    rows = [
        [project_name, "New Directory", "https://target.example/", NEW_URL, "PENDING", "Acme", ""],
    ]

    preview = _preview(authenticated_client, project_id, project_name, rows)

    stored = authenticated_client.get(f"{API}/imports/{preview['import_job_id']}/rows")
    assert stored.status_code == 200, stored.text
    body = stored.json()
    assert len(body) == 1
    assert body[0]["action"] == "CREATE"
    assert body[0]["row_number"] == 2


def test_an_unsupported_file_type_is_rejected(authenticated_client) -> None:
    response = authenticated_client.post(
        f"{API}/imports/preview",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"project_id": "does-not-matter"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_file"


def test_a_file_that_does_not_match_its_extension_is_rejected(authenticated_client) -> None:
    response = authenticated_client.post(
        f"{API}/imports/preview",
        files={"file": ("opportunities.xlsx", b"not a workbook", "application/octet-stream")},
        data={"project_id": "does-not-matter"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_file"
