"""Tests for the per website report sheet and the retry from a report."""

from __future__ import annotations

API = "/api/v1"


def _create_workspace(authenticated_client) -> tuple[str, str]:
    project = authenticated_client.post(
        f"{API}/projects",
        json={"name": "Report project", "target_website": "https://report.example"},
    ).json()
    project_id = project["id"]
    opportunity = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "opportunity_url": "https://report-directory.example/add",
            "name": "Report directory",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    ).json()
    return project_id, opportunity["id"]


def _queue(authenticated_client, opportunity_id: str) -> str:
    queued = authenticated_client.post(
        f"{API}/queue", json={"opportunity_ids": [opportunity_id], "type": "SUBMIT"}
    ).json()
    return queued["task_ids"][0]


def test_the_report_contains_a_sheet_per_website(authenticated_client) -> None:
    project_id, opportunity_id = _create_workspace(authenticated_client)
    _queue(authenticated_client, opportunity_id)

    job = authenticated_client.post(
        f"{API}/reports", json={"project_id": project_id, "format": "xlsx"}
    ).json()
    assert job["status"] == "COMPLETED", job

    import openpyxl

    workbook = openpyxl.load_workbook(job["file_path"])
    assert "Per website" in workbook.sheetnames, workbook.sheetnames

    sheet = workbook["Per website"]
    rows = list(sheet.iter_rows(values_only=True))
    header = [str(cell) for cell in rows[0]]
    assert "Domain" in header
    assert "Submitted" in header
    assert "Verified" in header
    assert "Failed" in header

    domains = [str(row[header.index("Domain")]) for row in rows[1:]]
    assert "report-directory.example" in domains


def test_the_csv_export_contains_the_website_rows(authenticated_client) -> None:
    project_id, opportunity_id = _create_workspace(authenticated_client)
    _queue(authenticated_client, opportunity_id)

    job = authenticated_client.post(
        f"{API}/reports", json={"project_id": project_id, "format": "csv"}
    ).json()
    assert job["status"] == "COMPLETED", job

    content = (authenticated_client.get(f"{API}/reports/{job['id']}/download").text)
    assert "report-directory.example" in content
    assert "Submitted" in content


def test_the_retry_requeues_the_failed_tasks_only(authenticated_client, db_session) -> None:
    from app.db.models import Task, TaskAttempt

    project_id, opportunity_id = _create_workspace(authenticated_client)
    task_id = _queue(authenticated_client, opportunity_id)

    task = db_session.get(Task, task_id)
    task.status = "FAILED"
    task.last_error = "the form was rejected"
    task.attempts = 1
    db_session.add(
        TaskAttempt(
            task_id=task_id,
            attempt_number=1,
            outcome="FAILED",
            error="the form was rejected",
            worker="test",
        )
    )
    db_session.commit()

    job = authenticated_client.post(
        f"{API}/reports", json={"project_id": project_id, "format": "xlsx"}
    ).json()

    response = authenticated_client.post(
        f"{API}/reports/{job['id']}/retry-failed", json={}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retried"] == 1
    assert body["task_ids"] == [task_id]

    db_session.expire_all()
    refreshed = db_session.get(Task, task_id)
    assert refreshed.status == "QUEUED"
    # The attempt history is not thrown away.
    attempts = db_session.query(TaskAttempt).filter_by(task_id=task_id).count()
    assert attempts == 1


def test_the_retry_is_idempotent(authenticated_client, db_session) -> None:
    from app.db.models import Task

    project_id, opportunity_id = _create_workspace(authenticated_client)
    task_id = _queue(authenticated_client, opportunity_id)

    task = db_session.get(Task, task_id)
    task.status = "FAILED"
    db_session.commit()

    job = authenticated_client.post(
        f"{API}/reports", json={"project_id": project_id, "format": "xlsx"}
    ).json()

    first = authenticated_client.post(f"{API}/reports/{job['id']}/retry-failed", json={}).json()
    assert first["retried"] == 1

    second = authenticated_client.post(f"{API}/reports/{job['id']}/retry-failed", json={}).json()
    # Nothing failed any more, so there is nothing to retry.
    assert second["retried"] == 0
    assert second["task_ids"] == []

    # No second task was created for the same work.
    from app.db.models import Task as TaskModel

    count = db_session.query(TaskModel).filter_by(opportunity_id=opportunity_id).count()
    assert count == 1


def test_the_retry_of_an_unknown_report_is_404(authenticated_client) -> None:
    response = authenticated_client.post(f"{API}/reports/does-not-exist/retry-failed", json={})
    assert response.status_code == 404


def test_the_retry_writes_an_activity_event(authenticated_client, db_session) -> None:
    from app.db.models import Task, TaskEvent

    project_id, opportunity_id = _create_workspace(authenticated_client)
    task_id = _queue(authenticated_client, opportunity_id)

    task = db_session.get(Task, task_id)
    task.status = "FAILED"
    db_session.commit()

    job = authenticated_client.post(
        f"{API}/reports", json={"project_id": project_id, "format": "xlsx"}
    ).json()
    authenticated_client.post(f"{API}/reports/{job['id']}/retry-failed", json={})

    db_session.expire_all()
    events = (
        db_session.query(TaskEvent)
        .filter_by(task_id=task_id, event_type="task.retry")
        .count()
    )
    assert events >= 1
