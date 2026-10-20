"""Security tests: SSRF protection, password hashing and JWT integrity."""

from __future__ import annotations

import base64
import json

import jwt
import pytest

from app.core.net import UnsafeUrlError, assert_public_url
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from tests.conftest import API

BLOCKED_URLS = [
    "http://127.0.0.1/",
    "http://127.0.0.1:8000/admin",
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost/",
    "http://[::1]/",
    "file:///etc/passwd",
    "ftp://example.com/file",
    "https://user:secret@example.com/",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_assert_public_url_rejects_dangerous_destinations(url) -> None:
    with pytest.raises(UnsafeUrlError):
        assert_public_url(url)


def test_assert_public_url_accepts_a_public_destination() -> None:
    # A public IP literal is used on purpose: no DNS lookup is performed.
    assert assert_public_url("https://93.184.216.34/page") == "https://93.184.216.34/page"


def test_assert_public_url_requires_a_url() -> None:
    with pytest.raises(UnsafeUrlError):
        assert_public_url("")


def test_the_api_rejects_a_non_http_opportunity_url(authenticated_client, project_id) -> None:
    response = authenticated_client.post(
        f"{API}/opportunities",
        json={
            "name": "Not a web page",
            "opportunity_url": "ftp://files.example.com/dump",
            "project_id": project_id,
        },
    )

    assert response.status_code in (400, 422), response.text


def test_password_hashing_round_trip() -> None:
    stored = hash_password("correct-horse-battery")

    assert stored != "correct-horse-battery"
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct-horse-battery", stored) is True
    assert verify_password("wrong-password", stored) is False
    assert verify_password("", stored) is False


def test_password_hashes_are_salted() -> None:
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")

    assert first != second
    assert verify_password("correct-horse-battery", first) is True
    assert verify_password("correct-horse-battery", second) is True


def test_verify_password_rejects_a_broken_hash() -> None:
    assert verify_password("correct-horse-battery", "not-a-hash") is False
    assert verify_password("correct-horse-battery", "") is False


def test_access_token_round_trip() -> None:
    token = create_access_token("user-123", {"email": "owner@example.com"})

    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["email"] == "owner@example.com"
    assert payload["exp"] > payload["iat"]


def test_a_tampered_payload_is_rejected() -> None:
    token = create_access_token("user-123")
    header, payload, signature = token.split(".")

    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = "admin-user"
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    )
    tampered = f"{header}.{tampered_payload}.{signature}"

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)


def test_a_tampered_signature_is_rejected() -> None:
    token = create_access_token("user-123")
    header, payload, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(f"{header}.{payload}.{flipped}")


def test_a_token_signed_with_another_secret_is_rejected() -> None:
    foreign = jwt.encode({"sub": "user-123", "exp": 9_999_999_999}, "another-secret", algorithm="HS256")

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(foreign)


def test_the_api_rejects_a_tampered_token(client, registered_user) -> None:
    token = registered_user["access_token"]
    header, payload, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

    response = client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {header}.{payload}.{flipped}"}
    )

    assert response.status_code == 401, response.text
