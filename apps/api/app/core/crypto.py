"""Encryption of sensitive values at rest.

The platform only stores the minimum: integration secrets are encrypted with
a key derived from the application secret, so a database dump never contains
a usable API key.

Construction: HMAC-SHA256 based counter mode keystream with an
encrypt-then-MAC tag (the tag covers nonce, ciphertext and the associated
data).  It is deliberately dependency free so the desktop sidecar stays small.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

VERSION = "v1"
_NONCE_BYTES = 16


def _derive_key(secret: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 120_000, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str, secret: str, associated_data: str = "") -> str:
    """Encrypt a string.  The result is safe to store in the database."""
    if plaintext == "":
        return ""
    salt = os.urandom(16)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(secret, salt)
    data = plaintext.encode("utf-8")
    stream = _keystream(key, nonce, len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, stream, strict=True))
    tag = hmac.new(key, nonce + ciphertext + associated_data.encode("utf-8"), hashlib.sha256).digest()
    payload = base64.b64encode(salt + nonce + tag + ciphertext).decode("ascii")
    return f"{VERSION}:{payload}"


def decrypt(payload: str, secret: str, associated_data: str = "") -> str:
    """Decrypt a value produced by :func:`encrypt`."""
    if not payload:
        return ""
    if not payload.startswith(f"{VERSION}:"):
        raise ValueError("Unsupported encrypted payload")
    raw = base64.b64decode(payload.split(":", 1)[1])
    salt = raw[:16]
    nonce = raw[16 : 16 + _NONCE_BYTES]
    tag = raw[16 + _NONCE_BYTES : 16 + _NONCE_BYTES + 32]
    ciphertext = raw[16 + _NONCE_BYTES + 32 :]
    key = _derive_key(secret, salt)
    expected = hmac.new(key, nonce + ciphertext + associated_data.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("The encrypted value failed the integrity check")
    stream = _keystream(key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode("utf-8")


def mask(value: str | None, visible: int = 4) -> str:
    """Return a masked representation that never reveals the secret."""
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return f"{'*' * 8}{value[-visible:]}"


def redact(payload: dict[str, Any], keys: tuple[str, ...] = ("api_key", "secret", "token", "password")) -> dict[str, Any]:
    """Replace secret looking values with a mask."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in keys and isinstance(value, str) and value:
            out[key] = mask(value)
        else:
            out[key] = value
    return out
