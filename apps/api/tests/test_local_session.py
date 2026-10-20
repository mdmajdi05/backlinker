"""Tests for the local (loopback) session of the desktop application.

The desktop app authenticates against its bundled backend with the shared
local token (``X-Local-Token``).  The session has to work on a completely
fresh database - the desktop app must not depend on a sign in and must not
race with the creation of the first user.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"
TOKEN = "local-token-for-tests"


@pytest.fixture
def local_client(tmp_path, monkeypatch):
    """A client whose backend knows the local token."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_token", TOKEN, raising=False)
    from app.main import app

    with TestClient(app) as client:
        yield client


def test_the_local_token_is_accepted(local_client) -> None:
    response = local_client.get(f"{API}/projects", headers={"X-Local-Token": TOKEN})
    assert response.status_code == 200, response.text


def test_a_missing_token_is_rejected(local_client) -> None:
    response = local_client.get(f"{API}/projects")
    assert response.status_code == 401, response.text


def test_a_wrong_token_is_rejected(local_client) -> None:
    response = local_client.get(f"{API}/projects", headers={"X-Local-Token": "wrong"})
    assert response.status_code == 401, response.text


def test_the_local_session_gets_a_user(local_client) -> None:
    response = local_client.get(f"{API}/auth/me", headers={"X-Local-Token": TOKEN})
    assert response.status_code == 200, response.text
    user = response.json()
    assert user["email"] == "local@autobacklinker.invalid"
    assert user["is_admin"] is True


def test_the_local_session_can_create_a_project(local_client) -> None:
    headers = {"X-Local-Token": TOKEN}
    project = local_client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": "Desktop project", "target_website": "https://desktop.example"},
    )
    assert project.status_code == 201, project.text

    listing = local_client.get(f"{API}/projects", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
