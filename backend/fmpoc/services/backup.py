"""v1.4.1 CR-023 / CR-024 / CR-025: encrypted backup and restore of the whole data set.

Backup file (.fmbak) - streaming, authenticated encryption with a passphrase (product owner Q2):

    b"FMBAK1" | uint16 header length | header JSON (kdf parameters, salt, nonce prefix, app version)
    then records: uint32 length | AES-256-GCM ciphertext of up to 1 MiB of a tar.gz stream
    key   = scrypt(passphrase, salt, n=2^15, r=8, p=1) -> 32 bytes
    nonce = 8-byte random prefix | uint32 record index
    AAD   = header bytes | uint64 record index | final flag      (binds header, order and the end of the stream)

The tar contains database/fmpoc.sqlite3 (consistent snapshot via SQLite's online backup API), attachments/**,
secrets/portable-encryption-key.json and manifest.json (versions, counts, SHA-256 of every file). config.toml, logs and
work folders are not included (Q13).

Restore (in-app reload, Q3): decrypt + verify into a work folder -> version/key checks -> maintenance mode (other API
calls answer 503) -> close all database connections -> move the current database/attachments/secrets into
pre-restore/ (only the latest safety copy is kept, Q14) -> move the restored data in -> migrate -> reopen the database
and reload the key -> revoke every session and trusted browser -> audit SYSTEM_RESTORED. Any failure after the swap
started moves the safety copy back.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import tarfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .. import VERSION, config
from ..security import crypto

log = logging.getLogger("fmpoc")

MAGIC = b"FMBAK1"
FORMAT = 1
CHUNK = 1 << 20
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
MIN_PASSPHRASE = 12
UPLOAD_CHUNK_MAX = 20 * 1024 * 1024  # client sends 20 MB parts (Cloudflare Tunnel limits requests to 100 MB)
WORK_DIR = "backup-work"
PRE_RESTORE_DIR = "pre-restore"
KEEP_SECONDS = 3600
DB_NAME = "fmpoc.sqlite3"


class BackupError(Exception):
    """User-facing error (message is safe to show)."""


# ------------------------------------------------------------------ crypto
def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


class _EncryptWriter:
    """File-like sink for tarfile's stream mode: buffers 1 MiB and writes encrypted records."""

    def __init__(self, out, key: bytes, header: bytes, prefix: bytes):
        self.out, self.aead, self.header, self.prefix = out, AESGCM(key), header, prefix
        self.buf, self.i, self.closed = bytearray(), 0, False

    def _emit(self, data: bytes, final: bool) -> None:
        nonce = self.prefix + self.i.to_bytes(4, "big")
        aad = self.header + self.i.to_bytes(8, "big") + (b"\x01" if final else b"\x00")
        ct = self.aead.encrypt(nonce, bytes(data), aad)
        self.out.write(len(ct).to_bytes(4, "big") + ct)
        self.i += 1

    def write(self, b) -> int:
        self.buf += b
        while len(self.buf) >= CHUNK:
            self._emit(self.buf[:CHUNK], False)
            del self.buf[:CHUNK]
        return len(b)

    def finish(self) -> None:
        self._emit(self.buf, True)
        self.buf = bytearray()


# ------------------------------------------------------------------ 1.9.0 (#62): key pair for scheduled backups
# The backup passphrase protects an X25519 private key (scrypt + AES-256-GCM). The application keeps the public key and
# the wrapped private key. Each scheduled backup gets a random 256-bit file key, wrapped for the public key (ephemeral
# X25519 + HKDF-SHA256 + AES-256-GCM); the header carries the wrapped private key too, so the file restores anywhere
# with the passphrase alone - but the running application, without the passphrase, cannot open its own backups.
_PRIV_AAD = b"pennywarden-backup-private-key:v1"
_DEK_INFO = b"pennywarden-backup-file-key:v1"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def new_keypair(passphrase: str) -> dict:
    priv = X25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(_derive(passphrase, salt, **SCRYPT)).encrypt(nonce, raw, _PRIV_AAD + pub)
    wrapped = {"kdf": "scrypt", **SCRYPT, "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct)}
    return {"public_key": _b64(pub), "wrapped_private_key": json.dumps(wrapped, separators=(",", ":")),
            "fingerprint": hashlib.sha256(pub).hexdigest()[:16]}


def unwrap_private_key(wrapped: dict, public_key_b64: str, passphrase: str) -> X25519PrivateKey:
    try:
        n, r, p = int(wrapped["n"]), int(wrapped["r"]), int(wrapped["p"])
        salt, nonce, ct = (base64.b64decode(wrapped[k]) for k in ("salt", "nonce", "ct"))
        pub = base64.b64decode(public_key_b64)
    except (KeyError, ValueError, TypeError):
        raise BackupError("The backup file header is damaged.") from None
    if n > 2 ** 20 or r > 16 or p > 4:
        raise BackupError("Unsupported backup format.")
    try:
        raw = AESGCM(_derive(passphrase, salt, n, r, p)).decrypt(nonce, ct, _PRIV_AAD + pub)
    except InvalidTag:
        raise BackupError("Wrong passphrase, or the file is not a valid backup.") from None
    return X25519PrivateKey.from_private_bytes(raw)


def _file_key_for(public_key_b64: str) -> tuple[bytes, dict]:
    pub = base64.b64decode(public_key_b64)
    eph = X25519PrivateKey.generate()
    epk = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    wk = HKDF(hashes.SHA256(), 32, None, _DEK_INFO + epk + pub).derive(eph.exchange(X25519PublicKey.from_public_bytes(pub)))
    dek, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    return dek, {"epk": _b64(epk), "dek_nonce": _b64(nonce), "wrapped_dek": _b64(AESGCM(wk).encrypt(nonce, dek, epk))}


def _file_key_from(h: dict, passphrase: str) -> bytes:
    try:
        wrapped = h["private_key"] if isinstance(h["private_key"], dict) else json.loads(h["private_key"])
        epk, nonce, wdek = (base64.b64decode(h[k]) for k in ("epk", "dek_nonce", "wrapped_dek"))
        pub = base64.b64decode(h["public_key"])
    except (KeyError, ValueError, TypeError):
        raise BackupError("The backup file header is damaged.") from None
    priv = unwrap_private_key(wrapped, h["public_key"], passphrase)
    wk = HKDF(hashes.SHA256(), 32, None, _DEK_INFO + epk + pub).derive(priv.exchange(X25519PublicKey.from_public_bytes(epk)))
    try:
        return AESGCM(wk).decrypt(nonce, wdek, epk)
    except InvalidTag:
        raise BackupError("The backup file is damaged (integrity check failed).") from None


def _read_exact(f, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise BackupError("The backup file is incomplete or damaged.")
    return b


def read_header(f) -> tuple[bytes, dict]:
    if f.read(len(MAGIC)) != MAGIC:
        raise BackupError("This is not a PennyWarden backup file (.fmbak).")
    hl = int.from_bytes(_read_exact(f, 2), "big")
    raw = _read_exact(f, hl)
    try:
        h = json.loads(raw)
    except ValueError:
        raise BackupError("The backup file header is damaged.") from None
    if h.get("format") != FORMAT or h.get("kdf") not in ("scrypt", "keypair"):
        raise BackupError("Unsupported backup format.")
    return MAGIC + hl.to_bytes(2, "big") + raw, h


def decrypt_file(src: Path, passphrase: str, dst: Path) -> dict:
    """Decrypts src into dst (tar.gz). Wrong passphrase / tampering / truncation raise BackupError."""
    with open(src, "rb") as f, open(dst, "wb") as out:
        header, h = read_header(f)
        if h["kdf"] == "keypair":   # 1.9.0 (#62): scheduled backup
            try:
                prefix = base64.b64decode(h["nonce_prefix"])
            except (KeyError, ValueError):
                raise BackupError("The backup file header is damaged.") from None
            aead = AESGCM(_file_key_from(h, passphrase))
        else:
            try:
                salt, prefix = base64.b64decode(h["salt"]), base64.b64decode(h["nonce_prefix"])
                n, r, p = int(h["n"]), int(h["r"]), int(h["p"])
            except (KeyError, ValueError):
                raise BackupError("The backup file header is damaged.") from None
            if n > 2 ** 20 or r > 16 or p > 4:  # refuse absurd KDF cost from a crafted file
                raise BackupError("Unsupported backup format.")
            aead = AESGCM(_derive(passphrase, salt, n, r, p))
        i, final = 0, False
        while not final:
            ln = f.read(4)
            if len(ln) != 4:
                raise BackupError("The backup file is incomplete (it ends early).")
            size = int.from_bytes(ln, "big")
            if size > CHUNK + 16:
                raise BackupError("The backup file is damaged.")
            ct = _read_exact(f, size)
            nonce = prefix + i.to_bytes(4, "big")
            for flag in (b"\x00", b"\x01"):
                try:
                    pt = aead.decrypt(nonce, ct, header + i.to_bytes(8, "big") + flag)
                    final = flag == b"\x01"
                    break
                except InvalidTag:
                    continue
            else:
                if i == 0:
                    raise BackupError("Wrong passphrase, or the file is not a valid backup.")
                raise BackupError("The backup file is damaged (integrity check failed).")
            out.write(pt)
            i += 1
        if f.read(1):
            raise BackupError("The backup file has unexpected data after its end.")
    return h


# ------------------------------------------------------------------ jobs (background thread + polled status)
@dataclass
class Job:
    id: str
    kind: str  # backup | restore
    state: str = "running"  # running | done | failed
    step: str = ""
    steps_done: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)

    def advance(self, step: str) -> None:
        if self.step:
            self.steps_done.append(self.step)
        self.step = step

    def out(self) -> dict:
        return {"id": self.id, "kind": self.kind, "state": self.state, "step": self.step,
                "steps_done": list(self.steps_done), "error": self.error,
                "result": {k: v for k, v in self.result.items() if not k.startswith("_")}}


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def new(self, kind: str) -> Job:
        with self.lock:
            now = time.time()
            for k in [k for k, j in self._jobs.items()
                      if j.state not in ("running", "choose") and now - j.created > KEEP_SECONDS]:
                self._jobs.pop(k, None)
            j = Job(secrets.token_urlsafe(24), kind)
            self._jobs[j.id] = j
            return j

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def running(self, kind: str | None = None) -> Job | None:
        # 2.2.0 (#319): a restore waiting for the What to restore choice counts as running
        return next((j for j in self._jobs.values() if j.state in ("running", "choose")
                     and (kind is None or j.kind == kind)), None)


def work_dir(settings) -> Path:
    d = settings.data_dir / WORK_DIR
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:  # pragma: no cover
        pass
    return d


def cleanup_work(settings, keep: set[str] | None = None) -> None:
    """Removes finished backup files / abandoned uploads older than an hour."""
    d = settings.data_dir / WORK_DIR
    if not d.is_dir():
        return
    now = time.time()
    for p in d.iterdir():
        if keep and p.name in keep:
            continue
        try:
            if now - p.stat().st_mtime > KEEP_SECONDS:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError:  # pragma: no cover
            pass


# ------------------------------------------------------------------ backup
def _slug(name: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "organization")[:40]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _snapshot_db(settings, dst: Path) -> None:
    src = sqlite3.connect(f"file:{settings.database_path.as_posix()}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(dst)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def _db_facts(db_path: Path) -> dict:
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        def one(sql):
            try:
                return con.execute(sql).fetchone()
            except sqlite3.Error:
                return None
        rev = one("SELECT version_num FROM alembic_version")
        ws = one("SELECT name, key_check FROM workspace WHERE bootstrap_completed_at IS NOT NULL ORDER BY id LIMIT 1")
        counts = {}
        for label, table in (("users", "app_user"), ("transactions", "register_transaction"),
                             ("attachments", "attachment"), ("fiscal_years", "fiscal_year"),
                             ("bank_accounts", "bank_account"), ("entities", "entity")):
            r = one(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed table names
            counts[label] = r[0] if r else 0
        return {"alembic_revision": rev[0] if rev else None, "workspace": ws[0] if ws else None,
                "key_check": ws[1] if ws else None, "counts": counts}
    finally:
        con.close()


def create_backup(settings, passphrase: str | None, job: Job | None = None,
                  keypair: dict | None = None) -> tuple[Path, str, dict]:
    """Writes an encrypted backup into the work folder. Returns (path, download name, manifest).
    keypair (1.9.0, #62): {"public_key", "wrapped_private_key"} of the scheduled backups instead of a passphrase."""
    wd = work_dir(settings)
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    snap = wd / f"snapshot-{secrets.token_hex(6)}.sqlite3"
    try:
        if job:
            job.advance("Taking a consistent copy of the database")
        _snapshot_db(settings, snap)
        facts = _db_facts(snap)
        name = f"{config.APP_NAME.lower()}-backup-{_slug(facts['workspace'] or 'organization')}-{stamp}.fmbak"
        files: list[tuple[str, Path]] = [(f"database/{DB_NAME}", snap)]
        key_file = crypto.key_path(settings.secrets_dir)
        if key_file.is_file():
            files.append((f"secrets/{crypto.KEY_FILENAME}", key_file))
        att = settings.attachments_dir
        if att.is_dir():
            for p in sorted(att.rglob("*")):
                if p.is_file():
                    files.append(("attachments/" + p.relative_to(att).as_posix(), p))
        if job:
            job.advance("Encrypting and writing the backup file")
        salt, prefix = secrets.token_bytes(16), secrets.token_bytes(8)
        if keypair:
            key, wrap = _file_key_for(keypair["public_key"])
            fields = {"kdf": "keypair", "public_key": keypair["public_key"],
                      "private_key": json.loads(keypair["wrapped_private_key"]), **wrap, "scheduled": True}
        else:
            key = _derive(passphrase, salt, **SCRYPT)
            fields = {"kdf": "scrypt", **SCRYPT, "salt": base64.b64encode(salt).decode()}
        hdr = json.dumps({"format": FORMAT, **fields,
                          "nonce_prefix": base64.b64encode(prefix).decode(), "cipher": "AES-256-GCM",
                          "chunk": CHUNK, "app_version": VERSION}, separators=(",", ":")).encode()
        header = MAGIC + len(hdr).to_bytes(2, "big") + hdr
        out_path = wd / f"{secrets.token_hex(12)}.fmbak"
        manifest_files = []
        with open(out_path, "wb") as out:
            out.write(header)
            w = _EncryptWriter(out, key, header, prefix)
            with tarfile.open(fileobj=w, mode="w|gz") as tar:  # type: ignore[arg-type]
                for arc, p in files:
                    manifest_files.append({"path": arc, "size": p.stat().st_size, "sha256": _sha256(p)})
                    ti = tar.gettarinfo(str(p), arcname=arc)
                    ti.uid = ti.gid = 0
                    ti.uname = ti.gname = ""
                    ti.mode = 0o600
                    with open(p, "rb") as fh:
                        tar.addfile(ti, fh)
                manifest = {"format": FORMAT, "app": config.APP_NAME, "app_version": VERSION,
                            "created_at": dt.datetime.utcnow().isoformat() + "Z",
                            "alembic_revision": facts["alembic_revision"], "workspace": facts["workspace"],
                            "counts": facts["counts"], "files": manifest_files}
                mb = json.dumps(manifest, indent=2).encode()
                ti = tarfile.TarInfo("manifest.json")
                ti.size, ti.mode, ti.mtime = len(mb), 0o600, int(time.time())
                tar.addfile(ti, io.BytesIO(mb))
            w.finish()
        return out_path, name, manifest
    finally:
        try:
            snap.unlink()
        except OSError:
            pass


# ------------------------------------------------------------------ restore: unpack and verify
ALLOWED = re.compile(r"^(manifest\.json|database/fmpoc\.sqlite3|secrets/portable-encryption-key\.json|"
                     r"attachments/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*)$")


def unpack(src: Path, passphrase: str, dest: Path, job: Job | None = None) -> dict:
    """Decrypts and safely extracts a backup into dest; verifies every file against the manifest."""
    if job:
        job.advance("Decrypting and checking the backup")
    dest.mkdir(parents=True, exist_ok=True)
    plain = dest / "backup.tar.gz"
    decrypt_file(src, passphrase, plain)
    data = dest / "data"
    seen: dict[str, str] = {}
    manifest = None
    try:
        with tarfile.open(plain, "r:gz") as tar:
            for m in tar:
                name = m.name
                if not m.isfile() or ".." in name.split("/") or not ALLOWED.match(name):
                    raise BackupError("The backup contains an unexpected file; it was not restored.")
                fh = tar.extractfile(m)
                if name == "manifest.json":
                    manifest = json.loads(fh.read(5_000_000))
                    continue
                target = data / name
                target.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with open(target, "wb") as out:
                    for b in iter(lambda: fh.read(1 << 20), b""):
                        h.update(b)
                        out.write(b)
                seen[name] = h.hexdigest()
    except (tarfile.TarError, OSError, ValueError, EOFError):
        raise BackupError("The backup content is damaged.") from None
    finally:
        try:
            plain.unlink()
        except OSError:
            pass
    if not manifest or manifest.get("format") != FORMAT:
        raise BackupError("The backup has no valid manifest.")
    expected = {f["path"]: f["sha256"] for f in manifest.get("files", [])}
    if expected != seen:
        raise BackupError("The backup content does not match its manifest (files missing or changed).")
    if f"database/{DB_NAME}" not in seen or f"secrets/{crypto.KEY_FILENAME}" not in seen:
        raise BackupError("The backup is missing the database or the encryption key.")
    return manifest


def check_compatible(data: Path, known_revisions: set[str]) -> dict:
    facts = _db_facts(data / "database" / DB_NAME)
    if facts["alembic_revision"] not in known_revisions:
        raise BackupError("This backup was made by a newer version of the application. Install that version (or a "
                          "later one) first, then restore.")
    if not facts["workspace"]:
        raise BackupError("The backup does not contain an initialized organization.")
    km = crypto.load_key(data / "secrets")
    if km is None or km.check_value != facts["key_check"]:
        raise BackupError("The encryption key in the backup does not match its database.")
    return facts


# ------------------------------------------------------------------ restore: swap
PARTS = ("database", "attachments", "secrets")


def swap_in(settings, data: Path) -> Path:
    """Moves current data to pre-restore/ (replacing an older safety copy) and the restored data into place."""
    pre = settings.data_dir / PRE_RESTORE_DIR
    if pre.exists():
        shutil.rmtree(pre)
    pre.mkdir()
    moved = []
    try:
        for part in PARTS:
            cur = settings.data_dir / part
            if cur.exists():
                os.replace(cur, pre / part)
                moved.append(part)
        for part in PARTS:
            src = data / part
            if src.exists():
                os.replace(src, settings.data_dir / part)
            else:
                (settings.data_dir / part).mkdir(parents=True, exist_ok=True)
        try:  # the key must stay private to the service account
            os.chmod(settings.secrets_dir, 0o700)
            for f in settings.secrets_dir.iterdir():
                os.chmod(f, 0o600)
        except OSError:  # pragma: no cover - Windows ACLs
            pass
        (pre / "README.txt").write_text(
            "Safety copy of the data that was in place before a restore on "
            f"{dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC. Only the latest copy is kept.\n", encoding="utf-8")
    except Exception:
        rollback(settings)
        raise
    return pre


def rollback(settings) -> None:
    """Puts the safety copy back (used when a restore fails after the swap started)."""
    pre = settings.data_dir / PRE_RESTORE_DIR
    for part in PARTS:
        saved = pre / part
        if saved.exists():
            cur = settings.data_dir / part
            if cur.exists():
                shutil.rmtree(cur)
            os.replace(saved, cur)
    try:
        os.chmod(settings.secrets_dir, 0o700)
    except OSError:  # pragma: no cover
        pass
