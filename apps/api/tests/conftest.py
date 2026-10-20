"""Shared fixtures for the Auto Backlinker API test suite.

The environment variables below are set **before** ``app.core.config`` is
imported, therefore the whole suite runs against a throw-away SQLite database
inside a temporary directory and never touches the developer's real data.

Every test starts with an empty database: the ``_clean_database`` fixture
truncates every table before and after each test, while the registry rows
(categories, adapters, discovery sources) are re-seeded by the application
lifespan every time a :class:`TestClient` is opened.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Environment - this has to happen before `app.core.config` is imported.
# ---------------------------------------------------------------------------
_DATA_DIR = tempfile.mkdtemp(prefix="abk-pytest-")
os.environ["AUTOBL_DATA_DIR"] = _DATA_DIR
os.environ["AUTOBL_ENVIRONMENT"] = "test"
os.environ["AUTOBL_SECRET_KEY"] = "pytest-secret-key-never-used-in-production"
os.environ["AUTOBL_WORKER_ENABLED"] = "false"
os.environ["AUTOBL_ALLOW_PRIVATE_NETWORK"] = "false"

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_session_factory, init_db  # noqa: E402
from app.main import app  # noqa: E402

API = "/api/v1"

DEFAULT_PASSWORD = "correct-horse-battery"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _truncate_all_tables() -> None:
    """Delete every row of every table (children first)."""
    engine = get_engine()
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


def register_user(
    client: TestClient,
    email: str = "operator@example.com",
    password: str = DEFAULT_PASSWORD,
    name: str = "Operator",
) -> dict:
    """Register a user through the API and return the token payload."""
    response = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    """Build the ``Authorization`` header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Session wide fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _data_dir() -> Iterator[Path]:
    """Remove the temporary data directory once the session is over."""
    yield Path(_DATA_DIR)
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_database() -> Iterator[None]:
    """Give every test an empty database (schema is created on demand)."""
    init_db()
    _truncate_all_tables()
    yield
    _truncate_all_tables()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A direct SQLAlchemy session for white-box assertions.

    The session is *not* transactional: a test that changes rows has to call
    ``db_session.commit()`` explicitly, and a test that reads rows created
    through the API should call ``db_session.rollback()`` first so the read
    starts from a fresh snapshot.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# HTTP clients
# ---------------------------------------------------------------------------
@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client with the application lifespan running (worker disabled)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def worker_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client with the **embedded worker enabled**.

    The worker is the only fixture that starts the background thread, so the
    other tests are never disturbed by a task being executed in the
    background.
    """
    monkeypatch.setattr(settings, "worker_enabled", True)
    monkeypatch.setattr(settings, "worker_poll_interval", 0.05)
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Users / authentication
# ---------------------------------------------------------------------------
@pytest.fixture
def registered_user(client: TestClient) -> dict:
    """A registered user (token payload)."""
    return register_user(client)


@pytest.fixture
def auth_headers(registered_user: dict) -> dict[str, str]:
    """The ``Authorization`` header of the primary test user."""
    return auth_header(registered_user["access_token"])


@pytest.fixture
def other_user(client: TestClient) -> dict:
    """A second user, used for the isolation tests."""
    return register_user(client, email="intruder@example.com", name="Intruder")


@pytest.fixture
def other_auth_headers(other_user: dict) -> dict[str, str]:
    """The ``Authorization`` header of the second test user."""
    return auth_header(other_user["access_token"])


@pytest.fixture
def authenticated_client(client: TestClient, auth_headers: dict[str, str]) -> Iterator[TestClient]:
    """The default client with the primary user's token attached."""
    original = dict(client.headers)
    client.headers.update(auth_headers)
    try:
        yield client
    finally:
        client.headers.clear()
        client.headers.update(original)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def project_id(authenticated_client: TestClient) -> str:
    """A project owned by the primary test user."""
    response = authenticated_client.post(
        f"{API}/projects",
        json={
            "name": "Acme Backlinks",
            "description": "Backlink campaign for Acme",
            "target_website": "https://acme.example",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def opportunity_id(authenticated_client: TestClient, project_id: str) -> str:
    """A manual opportunity inside :func:`project_id`."""
    response = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Directory Example",
            "opportunity_url": "https://directory.example.org/add-your-business",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
            "anchor_text": "Acme Analytics",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
