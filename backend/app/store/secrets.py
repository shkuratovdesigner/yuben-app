"""Local API-key storage (B1) — YouTube (data) + Anthropic (LLM) keys.

Write-only through the API: a key is stored on the machine and is NEVER returned
by any endpoint, logged, or placed in a URL / query string (PRD §8). The
``get_*_key`` readers are BACKEND-INTERNAL only (B3's key-test / pipeline; the
DirectAnthropicAdapter) — they are not exposed over HTTP.

Backend selection (per key, identical for both):
  * ``keyring`` (OS keychain) when importable and working — preferred.
  * else a local file ``<data_dir>/<name>.secret`` with ``0600`` perms.

``keyring`` is an OPTIONAL dependency; the import is guarded so the module works
without it. Set ``YUBEN_FORCE_FILE_SECRET=1`` to force the file backend (tests /
headless CI with no keychain).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from app.store.db import data_dir

try:  # optional dependency — make it importable-or-not
    import keyring  # type: ignore
    _HAS_KEYRING = True
except Exception:  # pragma: no cover - keyring absent in this environment
    keyring = None  # type: ignore
    _HAS_KEYRING = False

_SERVICE = "yuben"

# One (keyring-account, file-name, human-label) triple per stored secret.
_YOUTUBE: Tuple[str, str, str] = ("youtube_api_key", "youtube_key.secret", "YouTube key")
_ANTHROPIC: Tuple[str, str, str] = ("anthropic_api_key", "anthropic_key.secret", "Anthropic API key")


def _use_keyring() -> bool:
    if os.environ.get("YUBEN_FORCE_FILE_SECRET") == "1":
        return False
    return _HAS_KEYRING


def _key_file(name: str) -> Path:
    return data_dir() / name


def _write_file_key(name: str, value: str) -> None:
    path = str(_key_file(name))
    # Create/truncate with 0600 from the start; chmod again in case of umask.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, value.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - non-POSIX fallback
        pass


def _read_file_key(name: str) -> Optional[str]:
    try:
        raw = _key_file(name).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return raw or None


def _delete_file_key(name: str) -> None:
    try:
        _key_file(name).unlink()
    except FileNotFoundError:
        pass


def _set_secret(kind: Tuple[str, str, str], value: str) -> None:
    account, filename, label = kind
    value = (value or "").strip()
    if not value:
        raise ValueError("{} must be a non-empty string".format(label))
    if _use_keyring():
        try:
            keyring.set_password(_SERVICE, account, value)
            _delete_file_key(filename)  # avoid leaving a stale plaintext copy behind
            return
        except Exception:  # pragma: no cover - keychain unavailable at runtime
            pass  # fall back to the local file
    _write_file_key(filename, value)


def _get_secret(kind: Tuple[str, str, str]) -> Optional[str]:
    account, filename, _label = kind
    if _use_keyring():
        try:
            val = keyring.get_password(_SERVICE, account)
            if val:
                return val
        except Exception:  # pragma: no cover - keychain unavailable at runtime
            pass
    return _read_file_key(filename)


# --- YouTube Data API key ---------------------------------------------------
def set_youtube_key(value: str) -> None:
    """Store the YouTube key locally (write-only). Raises ValueError on empty input."""
    _set_secret(_YOUTUBE, value)


def get_youtube_key() -> Optional[str]:
    """BACKEND-INTERNAL: return the stored YouTube key, or None. Never expose via HTTP."""
    return _get_secret(_YOUTUBE)


def has_youtube_key() -> bool:
    """True when a YouTube key is stored. Safe to expose (boolean only)."""
    return bool(get_youtube_key())


# --- Anthropic API key (Phase 4 direct adapter) -----------------------------
def set_anthropic_key(value: str) -> None:
    """Store the Anthropic API key locally (write-only). Raises ValueError on empty."""
    _set_secret(_ANTHROPIC, value)


def get_anthropic_key() -> Optional[str]:
    """BACKEND-INTERNAL: return the stored Anthropic key, or None. Never expose via HTTP."""
    return _get_secret(_ANTHROPIC)


def has_anthropic_key() -> bool:
    """True when an Anthropic key is stored. Safe to expose (boolean only)."""
    return bool(get_anthropic_key())
