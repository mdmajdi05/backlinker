"""Device (local agent) tests: registration, api keys, claiming and heartbeats."""

from __future__ import annotations

from app.core.security import verify_password
from app.db.models import Device, TaskAttempt
from tests.conftest import API


def _register(client, name: str = "Agent One") -> dict:
    response = client.post(
        f"{API}/devices/register",
        json={"name": name, "platform": "linux", "version": "1.0.0", "capabilities": ["submit"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_register_device_returns_an_api_key(client) -> None:
    body = _register(client)

    assert body["device_id"]
    assert body["api_key"].startswith("agent_")
    assert body["poll_interval_seconds"] > 0


def test_the_api_key_is_only_stored_as_a_hash(client, db_session) -> None:
    body = _register(client)

    db_session.rollback()
    device = db_session.get(Device, body["device_id"])
    assert device is not None
    assert device.api_key_hash != body["api_key"]
    assert verify_password(body["api_key"], device.api_key_hash) is True


def test_listing_devices_requires_authentication(client) -> None:
    assert client.get(f"{API}/devices").status_code == 401


def test_claiming_a_task_with_the_wrong_key_returns_401(client) -> None:
    response = client.get(
        f"{API}/devices/tasks/claim", headers={"Authorization": "Bearer agent_wrong-key"}
    )

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthorized"


def test_claiming_a_task_without_a_key_returns_401(client) -> None:
    response = client.get(f"{API}/devices/tasks/claim")

    assert response.status_code == 401, response.text


def test_claiming_a_local_task_with_the_right_key(authenticated_client, client, project_id) -> None:
    device = _register(client)
    queued = authenticated_client.post(
        f"{API}/queue",
        json={
            "project_ids": [project_id],
            "type": "SUBMIT",
            "execution_environment": "LOCAL",
        },
    )
    assert queued.json()["created"] == 1

    response = client.get(
        f"{API}/devices/tasks/claim",
        headers={"Authorization": f"Bearer {device['api_key']}"},
    )

    assert response.status_code == 200, response.text
    task = response.json()
    assert task["id"]
    assert task["execution_environment"] == "LOCAL"
    assert task["status"] == "RUNNING"


def test_claiming_without_a_local_task_returns_no_content(client) -> None:
    device = _register(client)

    response = client.get(
        f"{API}/devices/tasks/claim",
        headers={"Authorization": f"Bearer {device['api_key']}"},
    )

    assert response.status_code == 204, response.text
    assert response.content == b""


def test_heartbeat_updates_last_seen_at(client, db_session) -> None:
    device = _register(client)

    db_session.rollback()
    stored = db_session.get(Device, device["device_id"])
    stored.last_seen_at = None
    db_session.commit()

    response = client.post(
        f"{API}/devices/{device['device_id']}/heartbeat",
        json={"status": "BUSY", "capabilities": ["submit", "verify"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True

    db_session.rollback()
    refreshed = db_session.get(Device, device["device_id"])
    assert refreshed.last_seen_at is not None
    assert refreshed.status == "BUSY"
    assert refreshed.capabilities == ["submit", "verify"]


def test_heartbeat_for_an_unknown_device_returns_404(client) -> None:
    response = client.post(
        f"{API}/devices/does-not-exist/heartbeat", json={"status": "ONLINE"}
    )

    assert response.status_code == 404, response.text


def test_reporting_a_task_result_moves_the_task(
    client, authenticated_client, project_id, db_session
) -> None:
    device = _register(client)
    queued = authenticated_client.post(
        f"{API}/queue",
        json={
            "project_ids": [project_id],
            "type": "SUBMIT",
            "execution_environment": "LOCAL",
        },
    )
    task_id = queued.json()["task_ids"][0]

    claimed = client.get(
        f"{API}/devices/tasks/claim",
        headers={"Authorization": f"Bearer {device['api_key']}"},
    )
    assert claimed.json()["id"] == task_id

    response = client.post(
        f"{API}/devices/tasks/{task_id}/report",
        json={"status": "SUCCEEDED", "result": {"submitted": True}},
        headers={"Authorization": f"Bearer {device['api_key']}"},
    )

    assert response.status_code == 200, response.text
    task = authenticated_client.get(f"{API}/tasks/{task_id}").json()
    assert task["status"] == "SUBMITTED"
    assert task["attempts"] == 1

    db_session.rollback()
    attempts = db_session.query(TaskAttempt).filter_by(task_id=task_id).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "SUCCEEDED"
    assert attempts[0].worker == f"device:{device['device_id']}"
