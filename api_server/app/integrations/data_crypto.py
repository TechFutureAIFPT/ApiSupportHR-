from __future__ import annotations

import base64
import json
import os
from typing import Any


_MAGIC = b"SHDS1"
_AAD = b"supporthr-data-secret-v1"


def _key() -> bytes:
    raw = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError("DATA_ENCRYPTION_KEY is required for encrypted data fields.")
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError as error:
        raise RuntimeError("DATA_ENCRYPTION_KEY must be valid base64.") from error
    if len(key) != 32:
        raise RuntimeError("DATA_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def encrypt_secret_payload(value: dict[str, Any]) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    plaintext = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _MAGIC + nonce + AESGCM(_key()).encrypt(nonce, plaintext, _AAD)


def decrypt_secret_payload(value: bytes | memoryview | None) -> dict[str, Any]:
    if value is None:
        return {}
    raw = bytes(value)
    if not raw.startswith(_MAGIC) or len(raw) < len(_MAGIC) + 13:
        raise RuntimeError("Encrypted data field has an unsupported format.")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    offset = len(_MAGIC)
    nonce = raw[offset : offset + 12]
    plaintext = AESGCM(_key()).decrypt(nonce, raw[offset + 12 :], _AAD)
    decoded = json.loads(plaintext.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {}
