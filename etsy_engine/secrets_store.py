"""Encrypted token store.

Etsy and Pinterest hand out new refresh tokens over time. GitHub Secrets cannot be
updated from inside a workflow, so the latest tokens are kept in data/tokens.enc,
encrypted with TOKEN_ENCRYPTION_KEY (a Fernet key that lives only in GitHub Secrets).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def fernet_key(secret: str) -> bytes:
    """Accept a real Fernet key, or any long passphrase (so it can be typed on a phone)."""
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    try:
        Fernet(secret.encode())
        return secret.encode()
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def generate_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


class TokenStore:
    def __init__(self, path: Path, key: str | None):
        self.path = Path(path)
        self.key = (key or "").strip()
        self._data: dict[str, Any] = {}
        self._fernet = None
        if self.key:
            from cryptography.fernet import Fernet

            self._fernet = Fernet(fernet_key(self.key))
        self._load()

    @property
    def persistent(self) -> bool:
        return self._fernet is not None

    def _load(self) -> None:
        if not self._fernet or not self.path.exists():
            return
        try:
            raw = self._fernet.decrypt(self.path.read_bytes())
            self._data = json.loads(raw.decode())
        except Exception as exc:  # wrong key or corrupted file
            log.warning("Could not decrypt %s (%s); starting with an empty token store", self.path, exc)
            self._data = {}

    def get(self, service: str) -> dict[str, Any]:
        return dict(self._data.get(service, {}))

    def set(self, service: str, values: dict[str, Any]) -> None:
        current = self._data.get(service, {})
        current.update({k: v for k, v in values.items() if v is not None})
        self._data[service] = current
        self._save()

    def _save(self) -> None:
        if not self._fernet:
            log.debug("TOKEN_ENCRYPTION_KEY not set; tokens kept in memory only")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._fernet.encrypt(json.dumps(self._data).encode()))
