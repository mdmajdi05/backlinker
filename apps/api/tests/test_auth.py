"""Authentication tests: registration, login and the ``/auth/me`` endpoint."""

from __future__ import annotations

import pytest

from app.core.security import create_access_token
from tests.conftest import API, DEFAULT_PASSWORD


def test_register_returns_201_and_a_token(client) -> None:
    response = client.post(
        f"{API}/auth/register",
        json={"email": "owner@example.com", "password": DEFAULT_PASSWORD, "name": "Owner"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0
    assert body["user"]["email"] == "owner@example.com"
    assert body["user"]["name"] == "Owner"
    assert body["user"]["is_active"] is True
    assert body["user"]["is_admin"] is False
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_rejects_a_duplicate_email(client) -> None:
    payload = {"email": "owner@example.com", "password": DEFAULT_PASSWORD, "name": "Owner"}
    assert client.post(f"{API}/auth/register", json=payload).status_code == 201

    duplicate = client.post(
        f"{API}/auth/register",
        json={"email": "owner@example.com", "password": "another-secret", "name": "Copycat"},
    )

    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "email_taken"


def test_register_validates_the_payload(client) -> None:
    short_password = client.post(
        f"{API}/auth/register",
        json={"email": "owner@example.com", "password": "short", "name": "Owner"},
    )
    invalid_email = client.post(
        f"{API}/auth/register",
        json={"email": "not-an-email", "password": DEFAULT_PASSWORD, "name": "Owner"},
    )
    missing_name = client.post(
        f"{API}/auth/register",
        json={"email": "owner@example.com", "password": DEFAULT_PASSWORD},
    )

    assert short_password.status_code == 422
    assert invalid_email.status_code == 422
    assert missing_name.status_code == 422


def test_login_with_the_wrong_password_returns_401(client) -> None:
    client.post(
        f"{API}/auth/register",
        json={"email": "owner@example.com", "password": DEFAULT_PASSWORD, "name": "Owner"},
    )

    response = client.post(
        f"{API}/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_with_unknown_email_returns_401(client) -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": "nobody@example.com", "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 401, response.text


def test_login_returns_a_token(client) -> None:
    client.post(
        f"{API}/auth/register",
        json={"email": "owner@example.com", "password": DEFAULT_PASSWORD, "name": "Owner"},
    )

    response = client.post(
        f"{API}/auth/login",
        json={"email": "owner@example.com", "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == "owner@example.com"


def test_me_returns_the_current_user(client, auth_headers) -> None:
    response = client.get(f"{API}/auth/me", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "operator@example.com"


def test_me_without_a_token_returns_401(client) -> None:
    response = client.get(f"{API}/auth/me")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_with_an_invalid_token_returns_401(client) -> None:
    response = client.get(
        f"{API}/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "invalid_token"


def test_me_with_an_expired_token_returns_401(client, registered_user) -> None:
    expired = create_access_token(registered_user["user"]["id"], expires_minutes=-5)

    response = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "bearer "},
    ],
)
def test_malformed_authorization_headers_are_rejected(client, header) -> None:
    response = client.get(f"{API}/auth/me", headers=header)

    assert response.status_code == 401, response.text
