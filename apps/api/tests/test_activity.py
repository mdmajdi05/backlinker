"""The activity log honours both ends of a date range."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import TaskEvent

API = "/api/v1"


def _event(db_session: Session, message: str, created_at: datetime) -> None:
    db_session.add(
        TaskEvent(
            event_type="test.event",
            message=message,
            level="INFO",
            created_at=created_at,
        )
    )
    db_session.commit()


def test_activity_filters_since_and_until(
    client: TestClient, auth_headers: dict, db_session: Session
) -> None:
    _event(db_session, "before", datetime(2026, 1, 1, 10, 0))
    _event(db_session, "inside", datetime(2026, 1, 2, 10, 0))
    _event(db_session, "after", datetime(2026, 1, 3, 10, 0))

    response = client.get(
        f"{API}/activity",
        params={
            "since": "2026-01-02T00:00:00Z",
            "until": "2026-01-02T23:59:59Z",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["message"] for item in items] == ["inside"]
    assert items[0]["created_at"].startswith("2026-01-02T10:00:00")
