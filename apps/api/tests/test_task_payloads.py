"""Regression tests for the task payload contract.

The payload of a task is stored as JSON, therefore it may only contain plain
values.  These tests guard the routes that build payloads against accidentally
passing an ORM object (which used to crash the request with a 500).
"""

from __future__ import annotations

import json

import pytest

API = "/api/v1"


def test_a_discovery_run_with_a_business_profile_is_accepted(
    authenticated_client, project_id
) -> None:
    """A project with a business profile must still be able to start a run."""
    profile = authenticated_client.post(
        f"{API}/profiles",
        json={
            "name": "Payload Profile",
            "primary_website": "https://payload.example",
            "keywords": ["analytics"],
            "excluded_domains": ["excluded.example"],
        },
    )
    assert profile.status_code == 201, profile.text

    project = authenticated_client.patch(
        f"{API}/projects/{project_id}",
        json={"business_profile_id": profile.json()["id"]},
    )
    assert project.status_code == 200, project.text

    run = authenticated_client.post(
        f"{API}/discovery/runs",
        json={
            "project_id": project_id,
            "provider": "manual_seed",
            "query": "analytics tools",
            "seeds": ["https://seed.example/submit"],
            "limit": 3,
        },
    )
    assert run.status_code == 202, run.text

    # The task payload must be JSON serialisable - it is stored in the column.
    from sqlalchemy import select

    from app.db.models import Task
    from app.db.session import session_scope

    with session_scope() as db:
        task = db.execute(select(Task).where(Task.type == "DISCOVER")).scalars().first()
        assert task is not None
        json.dumps(task.payload)  # must not raise


def test_a_task_payload_is_json_serialisable(authenticated_client, project_id) -> None:
    queued = authenticated_client.post(
        f"{API}/queue",
        json={"project_ids": [project_id], "type": "VERIFY"},
    )
    assert queued.status_code == 200, queued.text

    from sqlalchemy import select

    from app.db.models import Task
    from app.db.session import session_scope

    with session_scope() as db:
        task = db.execute(select(Task).where(Task.type == "VERIFY")).scalars().first()
        assert task is not None
        json.dumps(task.payload)


def test_enqueue_rejects_a_payload_that_cannot_be_serialised(db_session) -> None:
    from app.services.queue import enqueue

    with pytest.raises(ValueError, match="not JSON serialisable"):
        enqueue(
            db_session,
            task_type="SUBMIT",
            payload={"broken": object()},
            idempotency_key="not-serialisable",
        )
