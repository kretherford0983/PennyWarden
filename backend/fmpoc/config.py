"""Application configuration.

Precedence (docs/06 §11): built-in defaults < config file (APP_DATA_DIR/config.toml) < environment variables.
Secrets are never stored in the general configuration file; the portable encryption key lives in
APP_DATA_DIR/secrets/.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

APP_NAME = "PennyWarden"
# Earlier names of the default data folder, newest first: (Windows / macOS folder name, Linux folder name)
PREVIOUS_APP_NAMES = (("Fundwarden", "fundwarden"),                            # 1.6.6 - 1.6.8
                      ("FinancialManagementPOC", "financial-management-poc"))  # before 1.6.6
LEGACY_APP_NAME = PREVIOUS_APP_NAMES[-1][0]
VERSION = "2.3.0"


BUILD_INFO_FILE = Path(__file__).with_name("build_info.json")


def build_info() -> dict | None:
    """v1.4 CR-022: CI writes build_info.json into packaged builds (channel/branch, run number, commit)."""
    import json
    try:
        data = json.loads(BUILD_INFO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    keep = ("version", "branch", "commit", "run", "built_at")
    out = {k: str(data[k])[:64] for k in keep if data.get(k) not in (None, "")}
    local = local_time_text(out.get("built_at"))
    if local:
        out["built_at_local"] = local
    return out


def local_time_text(utc_text: str | None) -> str | None:
    """#185: an ISO UTC time in the time zone of the machine running PennyWarden (the user's computer in local mode,
    the server in server mode), e.g. "2026-10-10 4:15 PM CDT". None when it can't be read."""
    from datetime import datetime, timezone
    if not utc_text:
        return None
    try:
        t = datetime.fromisoformat(utc_text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    local = t.astimezone()
    zone = local.tzname() or ""
    if " " in zone:   # Windows names the zone in full ("Central Daylight Time"): use its initials
        zone = "".join(w[0] for w in zone.split() if w[:1].isalpha()).upper()
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local:%Y-%m-%d} {hour}:{local:%M} {local:%p} {zone}".strip()


def _default_data_dir(name: str, unix_name: str) -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / unix_name


def default_data_dir() -> Path:
    """OS-appropriate default application-data directory (separate from binaries, BR-086)."""
    return _default_data_dir(APP_NAME, "pennywarden")


def previous_default_data_dirs() -> list[Path]:
    """Default data directories under the application's earlier names, newest name first (1.7.0)."""
    return [_default_data_dir(name, unix_name) for name, unix_name in PREVIOUS_APP_NAMES]


def legacy_default_data_dir() -> Path:
    """The default data directory to adopt on a first start under the current name: the newest earlier name that
    has a folder (Fundwarden, 1.6.6 - 1.6.8; else Financial Management POC / Freedger, before 1.6.6). With none on
    disk, the newest earlier name."""
    dirs = previous_default_data_dirs()
    return next((d for d in dirs if d.is_dir()), dirs[0])


def adopt_legacy_data_dir(new: Path, old: Path) -> Path:
    """Renames (1.6.6, 1.7.0): a local installation that still has its data in the default folder of an earlier
    name keeps it - the folder is renamed once (same parent folder, nothing is copied or rewritten). If that is not
    possible (e.g. the folder is in use), the old folder is used where it is. Never called when the data directory
    was chosen explicitly."""
    if new.exists() or not old.is_dir():
        return new
    try:
        old.rename(new)
    except OSError as e:
        print(f"NOTE: using the existing data folder {old} (it could not be renamed to {new}: {e})", file=sys.stderr)
        return old
    print(f"Data folder renamed: {old} -> {new}", file=sys.stderr)
    return new


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    mode: str = "local"  # local | server
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    # Cookie "Secure" flag: auto = enabled when the request arrived over HTTPS
    secure_cookies: str = "auto"  # auto | true | false
    hsts: bool = False
    # Comma separated list of proxy IPs whose X-Forwarded-* headers are trusted ("" = none)
    trusted_proxies: str = ""
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    # per client address (and per unknown username): a brake on top of the per-account count below
    login_max_failures: int = 5
    login_lockout_seconds: int = 900
    # 1.8.0 (#113): failed attempts in a row per account (sign-in and Forgot password together), kept in the
    # database: locks at the three counts for the given minutes, the account is disabled at the last count.
    lockout_1_failures: int = 5
    lockout_1_minutes: int = 15
    lockout_2_failures: int = 10
    lockout_2_minutes: int = 60
    lockout_3_failures: int = 15
    lockout_3_minutes: int = 1440
    lockout_disable_failures: int = 20
    restore_max_mb: int = 20480  # v1.4.1 CR-024/025: largest backup file accepted for a restore
    # 1.9.0 (#62): server mode - the folders an Administrator may choose for scheduled backups (config.toml: a list;
    # FM_BACKUP_FOLDERS: separated by the system's path separator, ';' on Windows, ':' elsewhere)
    backup_folders: str = ""
    # 1.10.0 (#58): where the update check reads the release data files, and which channel it follows ("auto": from
    # the build - main builds stable, test builds test, other builds none; or stable | test | off)
    update_base_url: str = "https://pennywarden.org"
    update_channel: str = "auto"
    log_level: str = "INFO"
    debug: bool = False  # never enabled in packaged builds
    # 2.2.0 (#231): a test server. Only in config.toml / FM_TESTING_MODE (never from the web), and only in server mode:
    # a banner on every page and an Administrator's Testing tab that moves timers and schedules (services/testing.py)
    testing_mode: bool = False
    frontend_dir: Path | None = None

    @property
    def database_dir(self) -> Path:
        return self.data_dir / "database"

    @property
    def database_path(self) -> Path:
        return self.database_dir / "fmpoc.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.database_dir, self.attachments_dir, self.secrets_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.secrets_dir, 0o700)
        except OSError:  # pragma: no cover - platform dependent (Windows ACLs)
            pass


_BOOL_TRUE = {"1", "true", "yes", "on"}
_ENV_PREFIX = "FM_"


def _coerce(name: str, value, current):
    target = type(current) if current is not None else str
    if name == "data_dir" or name == "frontend_dir":
        return Path(str(value)) if value not in (None, "") else None
    if name == "backup_folders" and isinstance(value, (list, tuple)):
        return "\n".join(str(v) for v in value)
    if target is bool:
        return value if isinstance(value, bool) else str(value).strip().lower() in _BOOL_TRUE
    if target is int:
        return int(value)
    return str(value)


# 2.0.0 (#126): the command-line options the running process was started with (highest precedence), so the
# effective settings view can show each setting's source and lock the ones an edit could not change.
CLI_OVERRIDES: dict = {}
CONFIG_FILE = "config.toml"


def setting_sources(data_dir: Path, cli: dict | None = None) -> tuple[dict, dict]:
    """(raw values, source per setting) from config.toml, the environment and the command line - the same
    precedence as load_settings: default < config.toml < environment (FM_*) < command line."""
    values: dict = {}
    sources: dict = {}
    cfg = data_dir / CONFIG_FILE
    if cfg.is_file():
        try:
            with cfg.open("rb") as fh:
                for k, v in (tomllib.load(fh).get("server", {}) or {}).items():
                    values[k], sources[k] = v, "config.toml"
        except (OSError, tomllib.TOMLDecodeError):
            pass
    for f in fields(Settings):
        env = os.environ.get(_ENV_PREFIX + f.name.upper())
        if env is not None:
            values[f.name], sources[f.name] = env, "environment"
    for k, v in (CLI_OVERRIDES if cli is None else cli).items():
        if v is not None:
            values[k], sources[k] = v, "command line"
    return values, sources


def load_settings(overrides: dict | None = None) -> Settings:
    """Build settings from defaults, config file and environment (then explicit overrides e.g. CLI)."""
    global CLI_OVERRIDES
    CLI_OVERRIDES = {k: v for k, v in (overrides or {}).items() if v is not None}
    s = Settings()
    env_data_dir = os.environ.get(_ENV_PREFIX + "DATA_DIR")
    explicit = (overrides or {}).get("data_dir") or env_data_dir
    data_dir = Path(explicit) if explicit else adopt_legacy_data_dir(s.data_dir, legacy_default_data_dir())
    s = replace(s, data_dir=data_dir)
    values: dict = {}
    cfg = data_dir / "config.toml"
    if cfg.is_file():
        with cfg.open("rb") as fh:
            values.update(tomllib.load(fh).get("server", {}) or {})
    names = {f.name for f in fields(Settings)}
    for n in names:
        env = os.environ.get(_ENV_PREFIX + n.upper())
        if env is not None:
            values[n] = env
    for k, v in (overrides or {}).items():
        if v is not None:
            values[k] = v
    clean = {}
    for k, v in values.items():
        if k in names and k != "data_dir":
            clean[k] = _coerce(k, v, getattr(s, k))
    s = replace(s, **clean)
    if s.mode not in ("local", "server"):
        raise ValueError("mode must be 'local' or 'server'")
    if s.mode == "local" and "host" not in values:
        s = replace(s, host="127.0.0.1")
    return s


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")


def backup_folders(settings: Settings) -> list[str]:
    """1.9.0 (#62): the allowed scheduled-backup folders listed by the server owner."""
    raw = settings.backup_folders or ""
    parts = raw.split("\n") if "\n" in raw else raw.split(os.pathsep)
    return [p.strip() for p in parts if p.strip()]
