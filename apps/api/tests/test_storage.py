"""Storage tests: storage mode, connection checks, backups and migration preview."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import API


def test_storage_status_reports_the_local_mode(authenticated_client) -> None:
    response = authenticated_client.get(f"{API}/storage/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "LOCAL"
    assert body["database_type"] == "sqlite"
    assert body["connected"] is True
    assert body["cloud_connected"] is False
    assert body["conflicts"] == 0
    assert body["database_url_masked"].startswith("sqlite")


def test_storage_status_requires_authentication(client) -> None:
    assert client.get(f"{API}/storage/status").status_code == 401


def test_test_connection_rejects_a_bogus_url(authenticated_client) -> None:
    response = authenticated_client.post(
        f"{API}/storage/test", json={"database_url": "bogus://not-a-database"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["message"]


def test_test_connection_accepts_a_local_sqlite_url(authenticated_client, tmp_path) -> None:
    target = tmp_path / "candidate.db"

    response = authenticated_client.post(
        f"{API}/storage/test", json={"database_url": f"sqlite:///{target}"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["dialect"] == "sqlite"


def test_backup_creates_a_file(authenticated_client) -> None:
    response = authenticated_client.post(f"{API}/storage/backup")

    assert response.status_code == 200, response.text
    body = response.json()
    backup = Path(body["path"])
    assert backup.exists()
    assert backup.stat().st_size > 0
    assert body["label"] == "manual"

    history = authenticated_client.get(f"{API}/storage/history")
    assert history.status_code == 200, history.text
    assert any(item["path"] == body["path"] for item in history.json())


def test_migration_preview_returns_the_counts(authenticated_client, project_id) -> None:
    response = authenticated_client.get(f"{API}/storage/migration/preview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["projects"] == 1
    assert body["opportunities"] == 0
    assert body["tasks"] == 0
    assert body["backlink_records"] == 0
    assert body["profiles"] == 0
    assert body["compatible"] is False
    assert body["notes"]


def test_disconnect_keeps_the_local_data(authenticated_client, project_id) -> None:
    response = authenticated_client.post(f"{API}/storage/disconnect")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "LOCAL"
    assert body["cloud_connected"] is False

    projects = authenticated_client.get(f"{API}/projects")
    assert projects.status_code == 200, projects.text
    assert project_id in [item["id"] for item in projects.json()["items"]]

    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Still working",
            "opportunity_url": "https://directory.example.org/after-disconnect",
            "project_id": project_id,
        },
    )
    assert opportunity.status_code == 201, opportunity.text
