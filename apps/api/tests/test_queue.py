"""Queue tests: enqueueing, idempotency, task control, ordering and claiming."""

from __future__ import annotations

from app.db.models import Task
from app.db.repositories import TaskClaimRepository
from app.services import queue as queue_service
from tests.conftest import API


def test_enqueue_creates_a_task(authenticated_client, opportunity_id, project_id) -> None:
    response = authenticated_client.post(
        f"{API}/queue",
        json={"opportunity_ids": [opportunity_id], "type": "SUBMIT", "priority": 4},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 1
    assert len(body["task_ids"]) == 1

    task = authenticated_client.get(f"{API}/tasks/{body['task_ids'][0]}").json()
    assert task["status"] == "QUEUED"
    assert task["type"] == "SUBMIT"
    assert task["priority"] == 4
    assert task["project_id"] == project_id
    assert task["opportunity_id"] == opportunity_id
    assert task["attempts"] == 0
    assert task["max_attempts"] == 3


def test_enqueue_is_idempotent_for_the_same_opportunity(
    authenticated_client, opportunity_id
) -> None:
    first = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"}
    )
    second = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"}
    )

    assert first.json()["created"] == 1
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == 1
    assert second.json()["task_ids"] == []

    listing = authenticated_client.get(f"{API}/queue", params={"type": "SUBMIT"})
    assert listing.json()["total"] == 1


def test_enqueue_with_the_same_idempotency_key_returns_the_existing_task(db_session) -> None:
    task, created = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="stable-key"
    )
    assert created is True

    again, created_again = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="stable-key"
    )

    assert created_again is False
    assert again.id == task.id
    db_session.rollback()
    assert db_session.query(Task).filter_by(idempotency_key="stable-key").count() == 1


def test_bulk_control_pause_resume_cancel_and_retry(authenticated_client, opportunity_id) -> None:
    created = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"}
    )
    task_id = created.json()["task_ids"][0]

    paused = authenticated_client.post(
        f"{API}/queue/{task_id}/control", json={"action": "pause"}
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "DISCOVERED"

    resumed = authenticated_client.post(
        f"{API}/queue/{task_id}/control", json={"action": "resume"}
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "QUEUED"

    cancelled = authenticated_client.post(
        f"{API}/queue/{task_id}/control", json={"action": "cancel", "reason": "not needed"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["skip_reason"] == "not needed"

    retried = authenticated_client.post(f"{API}/queue/{task_id}/control", json={"action": "retry"})
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "QUEUED"
    assert retried.json()["finished_at"] is None


def test_bulk_control_applies_to_several_tasks(authenticated_client, project_id) -> None:
    created = authenticated_client.post(
        f"{API}/queue", json={"project_ids": [project_id], "type": "DISCOVER"}
    )
    task_ids = created.json()["task_ids"]
    assert len(task_ids) == 1

    response = authenticated_client.post(
        f"{API}/queue/bulk-control", json={"action": "cancel", "task_ids": task_ids}
    )

    assert response.status_code == 200, response.text
    assert response.json()["affected"] == 1
    task = authenticated_client.get(f"{API}/tasks/{task_ids[0]}").json()
    assert task["status"] == "CANCELLED"


def test_unknown_control_action_returns_400(authenticated_client, opportunity_id) -> None:
    created = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"}
    )
    task_id = created.json()["task_ids"][0]

    response = authenticated_client.post(
        f"{API}/queue/{task_id}/control", json={"action": "explode"}
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_action"


def test_reorder_changes_the_priority(authenticated_client, project_id, db_session) -> None:
    first = authenticated_client.post(
        f"{API}/queue", json={"project_ids": [project_id], "type": "DISCOVER"}
    ).json()["task_ids"][0]
    second = authenticated_client.post(
        f"{API}/queue",
        json={"project_ids": [project_id], "type": "EXPORT"},
    ).json()["task_ids"][0]

    response = authenticated_client.post(
        f"{API}/queue/reorder", json={"task_ids": [second, first]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2

    db_session.rollback()
    assert db_session.get(Task, second).priority == 2
    assert db_session.get(Task, first).priority == 1

    listing = authenticated_client.get(f"{API}/queue")
    assert [item["id"] for item in listing.json()["items"]] == [second, first]


def test_queue_stats_reflect_the_task_statuses(authenticated_client, opportunity_id) -> None:
    created = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"}
    )
    task_id = created.json()["task_ids"][0]

    stats = authenticated_client.get(f"{API}/queue/stats").json()
    assert stats["QUEUED"] == 1
    assert stats["TOTAL"] == 1
    assert stats["RUNNING"] == 0

    authenticated_client.post(f"{API}/queue/{task_id}/control", json={"action": "cancel"})

    stats = authenticated_client.get(f"{API}/queue/stats").json()
    assert stats["QUEUED"] == 0
    assert stats["CANCELLED"] == 1
    assert stats["TOTAL"] == 1


def test_a_task_can_only_be_claimed_once(db_session) -> None:
    task, _created = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="claim-once"
    )

    claimed = queue_service.claim_task(db_session, worker_id="worker-1")
    assert claimed is not None
    assert claimed.id == task.id
    assert claimed.status == "RUNNING"
    assert claimed.lease_owner == "worker-1"
    assert claimed.lease_expires_at is not None

    again = queue_service.claim_task(db_session, worker_id="worker-2")
    assert again is None


def test_claiming_marks_the_task_as_running(db_session) -> None:
    task, _created = queue_service.enqueue(
        db_session, task_type="VERIFY", idempotency_key="verify-once"
    )

    claimed = queue_service.claim_task(db_session, worker_id="worker-1")

    assert claimed is not None
    db_session.rollback()
    stored = db_session.get(Task, task.id)
    assert stored.status == "RUNNING"
    assert stored.started_at is not None


def test_a_task_with_a_future_schedule_is_not_claimed(db_session) -> None:
    from datetime import timedelta

    from app.db.base import utcnow

    _task, _created = queue_service.enqueue(
        db_session,
        task_type="SUBMIT",
        idempotency_key="scheduled-later",
        scheduled_for=utcnow() + timedelta(hours=1),
    )

    assert queue_service.claim_task(db_session, worker_id="worker-1") is None


def test_task_claim_repository_rejects_a_second_claim(db_session) -> None:
    task, _created = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="atomic-claim"
    )
    repo = TaskClaimRepository(db_session)

    claimed = repo.try_claim(task.id, "worker-1")
    assert claimed is not None
    assert repo.try_claim(task.id, "worker-2") is None
