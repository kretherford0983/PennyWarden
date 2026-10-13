"""2.0.0 (#124): server-recoverable backups.

A backup file is still locked only with the passphrase typed for it (the .fmbak format is unchanged). When "Let this
server recover the passphrase" is on, the server also writes a *recovery file*: the passphrase encrypted with the
**server key** (AES-256-GCM) and bound to that exact backup by its SHA-256 and a random id (both are the AAD, so a
recovery file can't be moved to another backup, and a different file with the same name does not match).

- The server key is 32 random bytes in `server-key/server.key` in the data folder, owner-only. It is machine-bound by
  design: it is never in a backup (backups hold the database, the attachments and the *portable* key only), never in
  logs, never shown or downloadable. A backup taken to another system can't be unlocked with it.
- Recovery files live in `backup-recovery/` (owner-only), outside the database, so a restore does not replace them.
- Only the server's command line (`pennywarden restore --use-server-key`) ever uses them; the web restore always asks
  for the passphrase.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_DIR = "server-key"
KEY_FILE = "server.key"
RECOVERY_DIR = "backup-recovery"
AAD_PREFIX = b"pennywarden-backup-recovery:v1:"
_ID = re.compile(r"^[a-f0-9]{32}$")
KINDS = ("MANUAL", "PRE_REINITIALIZE")


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - Windows ACLs
        pass
    return path


def _write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def server_key(settings, create: bool = True) -> bytes | None:
    p = settings.data_dir / KEY_DIR / KEY_FILE
    if p.is_file():
        raw = base64.b64decode(p.read_text(encoding="ascii").strip())
        if len(raw) != 32:
            raise ValueError("The server key file is damaged.")
        return raw
    if not create:
        return None
    _private_dir(settings.data_dir / KEY_DIR)
    key = secrets.token_bytes(32)
    _write_private(p, base64.b64encode(key) + b"\n")
    return key


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _aad(rid: str, sha: str) -> bytes:
    return AAD_PREFIX + rid.encode() + b":" + sha.encode()


def write_recovery(settings, backup_path: Path, filename: str, passphrase: str, created_by: str | None,
                   kind: str = "MANUAL", location: str | None = None) -> dict:
    """Writes the recovery file for a finished backup file. Returns its public metadata."""
    assert kind in KINDS
    key = server_key(settings)
    rid = secrets.token_hex(16)
    sha = file_sha256(backup_path)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, passphrase.encode("utf-8"), _aad(rid, sha))
    meta = {"id": rid, "filename": filename, "sha256": sha, "size": backup_path.stat().st_size,
            "created_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "created_by": created_by, "kind": kind, "location": location}
    rec = {**meta, "format": 1, "nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ct).decode()}
    d = _private_dir(settings.data_dir / RECOVERY_DIR)
    _write_private(d / f"{rid}.json", json.dumps(rec, indent=1).encode("utf-8"))
    return meta


def _records(settings) -> list[dict]:
    d = settings.data_dir / RECOVERY_DIR
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(r, dict) and _ID.match(str(r.get("id", ""))) and p.stem == r["id"]:
                out.append(r)
    return out


def public(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "filename", "sha256", "size", "created_at", "created_by", "kind", "location")}


def list_backups(settings) -> list[dict]:
    """Backups made on this server that the server can recover, newest first (never the secret part)."""
    return sorted((public(r) for r in _records(settings)), key=lambda r: r["created_at"] or "", reverse=True)


def passphrase_for(settings, backup_path: Path) -> str | None:
    """The passphrase of a backup file made on this server, or None (no matching recovery file, or another
    system's backup)."""
    key = server_key(settings, create=False)
    if key is None:
        return None
    sha = file_sha256(backup_path)
    for r in _records(settings):
        if r.get("sha256") != sha:
            continue
        try:
            return AESGCM(key).decrypt(base64.b64decode(r["nonce"]), base64.b64decode(r["ciphertext"]),
                                       _aad(r["id"], sha)).decode("utf-8")
        except (InvalidTag, ValueError, KeyError):
            continue
    return None


class RecoveryError(Exception):
    pass


def remove_recovery(settings, rid: str) -> dict:
    """Makes a backup passphrase-only. A reinitialize's safety backup can't be made unrecoverable from the web."""
    if not _ID.match(rid or ""):
        raise RecoveryError("not found")
    p = settings.data_dir / RECOVERY_DIR / f"{rid}.json"
    r = next((x for x in _records(settings) if x["id"] == rid), None)
    if r is None or not p.is_file():
        raise RecoveryError("not found")
    if r.get("kind") == "PRE_REINITIALIZE":
        raise RecoveryError("protected")
    p.unlink()
    return public(r)
