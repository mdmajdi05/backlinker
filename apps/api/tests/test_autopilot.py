"""Auto pilot tests: approving queues the submission, the sweep stays in control.

The auto pilot is what turns "approve" into "the system keeps submitting":
when it is enabled for a project, every approved opportunity of that project
is queued for submission - exactly once.
"""

from __future__ import annotations

from app.db.models import Opportunity, Task
from app.services import autopilot
from tests.conftest import API


def _approve(db_session, opportunity_id: str) -> None:
    """Approve an opportunity (the way the registry bulk action does)."""
    db_session.rollback()
    opportunity = db_session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    opportunity.status = "APPROVED"
    db_session.commit()


def _tasks(db_session, project_id: str) -> list[Task]:
    db_session.rollback()
    return (
        db_session.query(Task)
        .filter(Task.project_id == project_id, Task.type == "SUBMIT")
        .all()
    )


def _enable(client, project_id: str, categories: list[str] | None = None) -> dict:
    """Switch the auto pilot of a project on."""
    response = client.post(
        f"{API}/projects/{project_id}/autopilot",
        json={"enabled": True, "categories": categories or []},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bulk_approve(client, opportunity_ids: list[str]) -> dict:
    response = client.post(
        f"{API}/opportunities/bulk",
        json={"opportunity_ids": opportunity_ids, "action": "approve"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# Approving
# --------------------------------------------------------------------------
def test_bulk_approving_queues_nothing_when_the_autopilot_is_off(
    authenticated_client, db_session, project_id, opportunity_id
) -> None:
    result = _bulk_approve(authenticated_client, [opportunity_id])

    assert result["affected"] == 1
    assert _tasks(db_session, project_id) == []


def test_bulk_approving_queues_exactly_one_task_when_the_autopilot_is_on(
    authenticated_client, db_session, project_id, opportunity_id
) -> None:
    _enable(authenticated_client, project_id)

    result = _bulk_approve(authenticated_client, [opportunity_id])

    assert result["affected"] == 1
    tasks = _tasks(db_session, project_id)
    assert len(tasks) == 1
    assert tasks[0].type == "SUBMIT"
    assert tasks[0].opportunity_id == opportunity_id
    assert tasks[0].status == "QUEUED"


def test_bulk_approving_twice_does_not_create_a_second_task(
    authenticated_client, db_session, project_id, opportunity_id
) -> None:
    _enable(authenticated_client, project_id)

    _bulk_approve(authenticated_client, [opportunity_id])
    _bulk_approve(authenticated_client, [opportunity_id])

    assert len(_tasks(db_session, project_id)) == 1


def test_approving_queues_nothing_when_the_autopilot_is_off(
    db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)

    created = autopilot.queue_approved(db_session, project_id)

    assert created == []
    assert _tasks(db_session, project_id) == []


def test_approving_queues_exactly_one_task_when_the_autopilot_is_on(
    db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)
    autopilot.set_auto_submit(db_session, project_id, True)

    created = autopilot.queue_approved(db_session, project_id)

    assert len(created) == 1
    task = created[0]
    assert task.type == "SUBMIT"
    assert task.opportunity_id == opportunity_id
    assert task.project_id == project_id
    assert task.status == "QUEUED"
    assert len(_tasks(db_session, project_id)) == 1


def test_queueing_twice_does_not_create_a_second_task(
    db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)
    autopilot.set_auto_submit(db_session, project_id, True)

    first = autopilot.queue_approved(db_session, project_id)
    second = autopilot.queue_approved(db_session, project_id)

    assert len(first) == 1
    assert second == []
    assert len(_tasks(db_session, project_id)) == 1


def test_the_queue_respects_the_category_filter(
    db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)
    autopilot.set_auto_submit(db_session, project_id, True, ["LOCAL_CITATION"])

    created = autopilot.queue_approved(db_session, project_id)

    assert created == []
    assert _tasks(db_session, project_id) == []


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------
def test_the_sweep_never_touches_a_project_without_the_setting(
    db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)

    result = autopilot.sweep(db_session)

    assert result["queued"] == 0
    assert _tasks(db_session, project_id) == []


def test_the_sweep_queues_the_approved_opportunities(
    db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)
    autopilot.set_auto_submit(db_session, project_id, True)

    result = autopilot.sweep(db_session)

    assert result["projects"] == 1
    assert result["queued"] == 1
    assert len(_tasks(db_session, project_id)) == 1


def test_the_sweep_is_idempotent(db_session, project_id, opportunity_id) -> None:
    _approve(db_session, opportunity_id)
    autopilot.set_auto_submit(db_session, project_id, True)

    autopilot.sweep(db_session)
    autopilot.sweep(db_session)

    assert len(_tasks(db_session, project_id)) == 1


def test_the_worker_sweeps_the_autopilot(monkeypatch) -> None:
    """The worker calls the sweep - that is what keeps the submissions going."""
    from app.workers.runner import Worker

    calls: list[dict] = []

    def fake_sweep(db):
        calls.append({"projects": 0, "queued": 0})
        return {"projects": 0, "queued": 0}

    monkeypatch.setattr(autopilot, "sweep", fake_sweep)
    worker = Worker(worker_id="test-worker")
    for _ in range(5):
        worker.tick()

    assert calls, "the worker did not call the auto pilot sweep"


def test_the_sweep_ignores_opportunities_that_are_not_approved(
    db_session, project_id, opportunity_id
) -> None:
    autopilot.set_auto_submit(db_session, project_id, True)

    result = autopilot.sweep(db_session)

    assert result["queued"] == 0
    assert _tasks(db_session, project_id) == []


# --------------------------------------------------------------------------
# The endpoints
# --------------------------------------------------------------------------
def test_the_autopilot_is_off_by_default(authenticated_client, project_id) -> None:
    response = authenticated_client.get(f"{API}/projects/{project_id}/autopilot")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["categories"] == []
    assert body["pending"] == 0


def test_the_autopilot_can_be_enabled_and_disabled(
    authenticated_client, project_id
) -> None:
    enabled = authenticated_client.post(
        f"{API}/projects/{project_id}/autopilot",
        json={"enabled": True, "categories": ["BUSINESS_DIRECTORY"]},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert enabled.json()["categories"] == ["BUSINESS_DIRECTORY"]

    disabled = authenticated_client.post(
        f"{API}/projects/{project_id}/autopilot",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False


def test_enabling_the_autopilot_queues_the_approved_opportunities(
    authenticated_client, db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)

    response = authenticated_client.post(
        f"{API}/projects/{project_id}/autopilot", json={"enabled": True}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    # The approved opportunity was queued right away.
    assert body["queued"] == 1
    assert body["pending"] == 0
    assert len(_tasks(db_session, project_id)) == 1


def test_the_pending_count_reports_the_approved_opportunities(
    authenticated_client, db_session, project_id, opportunity_id
) -> None:
    _approve(db_session, opportunity_id)
    autopilot.set_auto_submit(db_session, project_id, True)

    response = authenticated_client.get(f"{API}/projects/{project_id}/autopilot")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["waiting"] == 1
    assert body["pending"] == 1


def test_a_foreign_project_cannot_change_the_autopilot(
    authenticated_client, other_auth_headers
) -> None:
    their_project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Foreign project", "target_website": "https://foreign.example"},
        headers=other_auth_headers,
    )
    assert their_project.status_code == 201, their_project.text

    response = authenticated_client.post(
        f"{API}/projects/{their_project.json()['id']}/autopilot", json={"enabled": True}
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "forbidden"
