#!/usr/bin/env bash
# Install or upgrade PennyWarden as an always-on systemd service (native, no Docker).
#
#   sudo ./install-server.sh PennyWarden-linux-x64-portable.tar.gz [--port 8765]
#
# Layout:  /opt/pennywarden/releases/<timestamp>/  binaries (replaceable)   /opt/pennywarden/current -> active release
#          /var/lib/pennywarden/                    APP_DATA_DIR: database, attachments, secrets, logs, config.toml
#          /var/backups/pennywarden/                automatic data snapshot taken before every upgrade
# The app listens on 127.0.0.1 by default (host / Bind Address in config.toml); publish it through Cloudflare Tunnel or
# a local HTTPS reverse proxy. 2.1.0 (#236): the health check and the final message use the configured Bind Address.
#
# The application was renamed twice: 1.7.0 - PennyWarden (1.6.6 to 1.6.8: service "fundwarden", /opt/fundwarden,
# /var/lib/fundwarden) and 1.6.6 - Fundwarden (before: service "fmpoc", /opt/fmpoc, /var/lib/fmpoc). When this
# installer finds an installation under an earlier name and no PennyWarden data yet, it MIGRATES it: the old service
# is stopped and disabled and its data directory is COPIED to /var/lib/pennywarden. Nothing of the old installation
# is changed or removed, so going back is
#   systemctl disable --now pennywarden; systemctl enable --now fundwarden      (or fmpoc)
# Remove the old installation by hand once you are satisfied (docs/upgrade.md, "Cleanup after the rename").
set -euo pipefail
TARBALL="${1:-}"; shift || true
PORT=""
while [ $# -gt 0 ]; do case "$1" in --port) PORT="$2"; shift 2;; *) echo "unknown option $1"; exit 2;; esac; done
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
[ -f "$TARBALL" ] || { echo "usage: sudo $0 <PennyWarden-linux-x64-portable.tar.gz> [--port N]"; exit 2; }
command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }

SVC=pennywarden; USER_=pennywarden; OPT=/opt/pennywarden; DATA=/var/lib/pennywarden; BK=/var/backups/pennywarden
PREVIOUS="fundwarden fmpoc"   # earlier names, newest first: fundwarden = 1.6.6 to 1.6.8, fmpoc = before 1.6.6
STAMP="$(date +%Y%m%d-%H%M%S)"; REL="$OPT/releases/$STAMP"
set_old() { OLD_SVC="$1"; OLD_OPT="/opt/$1"; OLD_DATA="/var/lib/$1"; OLD_BK="/var/backups/$1"; }

MIGRATE=0; set_old fundwarden
if [ ! -d "$DATA/database" ]; then
  # no PennyWarden data yet: migrate the installation that is in service; if none is running, the newest name
  # that has data (a server can still hold the stopped fmpoc installation next to the Fundwarden one)
  for n in $PREVIOUS; do
    if [ -d "/var/lib/$n/database" ] && systemctl is-active --quiet "$n"; then MIGRATE=1; set_old "$n"; break; fi
  done
  if [ "$MIGRATE" = 0 ]; then
    for n in $PREVIOUS; do
      if [ -d "/var/lib/$n/database" ]; then MIGRATE=1; set_old "$n"; break; fi
    done
  fi
else
  for n in $PREVIOUS; do
    if systemctl is-active --quiet "$n"; then
      echo "Both a PennyWarden installation ($DATA) and a RUNNING old '$n' service exist."
      echo "Decide which one is current first:"
      echo "  keep PennyWarden:          sudo systemctl disable --now $n     (then run this installer again)"
      echo "  migrate the old one again: stop here, move $DATA away, then run this installer again"
      exit 1
    fi
  done
fi

id "$USER_" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$USER_"
install -d -m 0755 "$OPT/releases"

echo "==> unpacking release $STAMP"
install -d -m 0755 "$REL"
tar -xzf "$TARBALL" -C "$REL" --strip-components=1 --no-same-owner
chown -R root:root "$REL"; chmod -R go-w "$REL"
"$REL/pennywarden" --version >/dev/null
# 2.1.0 (#237): check the existing config.toml with the new release BEFORE anything is stopped or migrated
CHECK_DIR="$DATA"; [ "$MIGRATE" = 1 ] && CHECK_DIR="$OLD_DATA"
if [ -f "$CHECK_DIR/config.toml" ] && ! "$REL/pennywarden" apply-config --dry-run --data-dir "$CHECK_DIR" >/dev/null; then
  echo "Fix $CHECK_DIR/config.toml (see above) and run the installer again."
  rm -rf "$REL"; exit 1
fi

if [ "$MIGRATE" = 1 ]; then
  echo "==> found an installation under the old name ($OLD_SVC, $OLD_DATA): migrating it to PennyWarden"
  NEED=$(du -sk "$OLD_DATA" | cut -f1); AVAIL=$(df -Pk "$(dirname "$DATA")" | awk 'NR==2 {print $4}')
  if [ "$AVAIL" -lt $((NEED + NEED / 10 + 10240)) ]; then
    echo "not enough free space in $(dirname "$DATA") to copy $OLD_DATA (needs about $((NEED / 1024 + 10)) MB) - nothing was changed"
    rm -rf "$REL"; exit 1
  fi
  OLD_WAS_ACTIVE=0; systemctl is-active --quiet "$OLD_SVC" && OLD_WAS_ACTIVE=1
  undo_migration() {
    echo "==> migration failed - the old installation is unchanged; putting it back in service"
    rm -rf "$DATA.migrating"
    [ "$OLD_WAS_ACTIVE" = 1 ] && systemctl start "$OLD_SVC" || true
  }
  trap undo_migration ERR
  echo "    stopping $OLD_SVC and copying $OLD_DATA -> $DATA (the old directory is left untouched)"
  systemctl stop "$OLD_SVC" 2>/dev/null || true
  rm -rf "$DATA.migrating"
  [ -d "$DATA" ] && rmdir "$DATA"          # only an empty leftover is acceptable here
  cp -a "$OLD_DATA" "$DATA.migrating"
  diff -rq "$OLD_DATA" "$DATA.migrating" >/dev/null   # every file identical before we switch
  chown -R "$USER_:$USER_" "$DATA.migrating"; chmod 0700 "$DATA.migrating"
  mv "$DATA.migrating" "$DATA"
  trap - ERR
  systemctl disable "$OLD_SVC" >/dev/null 2>&1 || true
elif [ -d "$DATA/database" ]; then
  echo "==> stopping the service and snapshotting data to $BK/$STAMP"
  systemctl stop "$SVC" 2>/dev/null || true
  install -d -m 0700 "$BK"; cp -a "$DATA" "$BK/$STAMP"
fi
install -d -m 0700 -o "$USER_" -g "$USER_" "$DATA"

if [ ! -f "$DATA/config.toml" ]; then
  [ -n "$PORT" ] || PORT=8765
  echo "==> writing $DATA/config.toml"
  cat > "$DATA/config.toml" <<CFG
# PennyWarden - server settings (see docs/configuration.md)
[server]
mode = "server"
host = "127.0.0.1"          # loopback only; Cloudflare Tunnel / reverse proxy connects locally
port = $PORT
secure_cookies = "true"     # browsers reach the app over HTTPS (Cloudflare edge)
trusted_proxies = "127.0.0.1"
# folders an Administrator may choose for scheduled backups, as a list, e.g.
#   backup_folders = ["/srv/pennywarden-backups", "/mnt/nas/pennywarden"]
# They must be outside /home. After changing this list run: sudo pennywarden apply-config
backup_folders = []
CFG
  chown "$USER_:$USER_" "$DATA/config.toml"; chmod 0600 "$DATA/config.toml"
fi
# --port only sets the port of a NEW config.toml; an existing one is never changed by an upgrade. The health check
# reads host and port from config.toml (2.1.0, #236: apply-config --show-url).

cat > /etc/systemd/system/$SVC.service <<UNIT
[Unit]
Description=PennyWarden
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_
Group=$USER_
ExecStart=$OPT/current/pennywarden --mode server --no-browser --data-dir $DATA
Restart=on-failure
RestartSec=3
UMask=0077
Environment=PYTHONDONTWRITEBYTECODE=1
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$DATA
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictNamespaces=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
UNIT

ln -sfn "$REL" "$OPT/current"
# 2.0.0 build 13: the host commands (sudo pennywarden restore | reinitialize | reset-password | reset-mfa ...) on the
# PATH. A wrapper, not a symlink: it always runs the current release.
CMD=/usr/local/bin/pennywarden
if [ ! -e "$CMD" ] || grep -q "PennyWarden host-command wrapper" "$CMD" 2>/dev/null; then
  install -d -m 0755 /usr/local/bin
  cat > "$CMD.tmp" <<CMDSH
#!/bin/sh
# PennyWarden host-command wrapper (written by install-server.sh). Run with sudo, e.g.:
#   sudo pennywarden restore --list
exec $OPT/current/pennywarden "\$@"
CMDSH
  chmod 0755 "$CMD.tmp" && mv -f "$CMD.tmp" "$CMD"
else
  echo "NOTE: $CMD exists and was not written by this installer; left unchanged (use $OPT/current/pennywarden)."
fi
# 2.0.0 build 13: the service may write only to its data folder (ProtectSystem=strict), so the scheduled-backup folders
# in config.toml (backup_folders) are added to its write list in the drop-in pennywarden.service.d/backup-folders.conf.
# 2.1.0 (#237): written by the same command the server owner runs after changing backup_folders, so the two can't
# drift apart. A manual "systemctl edit" override is left alone.
if ! "$REL/pennywarden" apply-config --no-restart --installer --data-dir "$DATA"; then
  echo "==> apply-config failed - fix $DATA/config.toml, then: sudo pennywarden apply-config"
  if [ "$MIGRATE" = 1 ]; then
    systemctl disable --now "$SVC" >/dev/null 2>&1 || true
    mv "$DATA" "$DATA.failed-migration-$STAMP"
    systemctl enable --now "$OLD_SVC" >/dev/null 2>&1 || true
    echo "    the old service '$OLD_SVC' is running again on its unchanged data; the copy is in $DATA.failed-migration-$STAMP"
  fi
  exit 1
fi
# 2.1.0 (#236): connect to the configured Bind Address (0.0.0.0 -> 127.0.0.1, a specific address as is)
URL="$("$REL/pennywarden" apply-config --show-url --data-dir "$DATA")"
systemctl daemon-reload
systemctl enable --now "$SVC" >/dev/null
systemctl restart "$SVC"

echo -n "==> waiting for health"
for i in $(seq 1 60); do
  if "$REL/python/bin/python3" -c "import urllib.request,sys; urllib.request.urlopen('$URL/api/health', timeout=2)" 2>/dev/null; then echo " OK"; break; fi
  echo -n "."; sleep 1
  if [ "$i" = 60 ]; then
    echo " FAILED"; journalctl -u "$SVC" -n 40 --no-pager || true
    if [ "$MIGRATE" = 1 ]; then
      echo "==> PennyWarden did not start after the migration - switching back to the old installation"
      systemctl disable --now "$SVC" >/dev/null 2>&1 || true
      mv "$DATA" "$DATA.failed-migration-$STAMP"
      systemctl enable --now "$OLD_SVC" >/dev/null 2>&1 || true
      echo "    the old service '$OLD_SVC' is running again on its unchanged data; the copy is in $DATA.failed-migration-$STAMP"
    fi
    exit 1
  fi
done
# keep the three newest releases
ls -1dt "$OPT"/releases/* | tail -n +4 | xargs -r rm -rf
"$REL/python/bin/python3" -c "import urllib.request; print(urllib.request.urlopen('$URL/api/system/status').read().decode())"
echo "Installed. Service: systemctl status $SVC | logs: journalctl -u $SVC -f | data: $DATA"
echo "Host commands: sudo pennywarden restore --list | restore FILE | reinitialize | reset-password --user NAME | reset-mfa --user NAME (add --data-dir $DATA)"
echo "After changing config.toml (e.g. backup_folders): sudo pennywarden apply-config"
"$REL/pennywarden" apply-config --show-endpoints --data-dir "$DATA"
if [ "$MIGRATE" = 1 ]; then
  echo
  echo "MIGRATED from the old name. Your tunnel/reverse proxy needs no change (same port)."
  echo "The old installation was left in place, stopped and disabled, so you can go back:"
  echo "    sudo systemctl disable --now $SVC && sudo systemctl enable --now $OLD_SVC"
fi
for n in $PREVIOUS; do
  if [ -e "/var/lib/$n" ] || [ -e "/opt/$n" ] || [ -e "/var/backups/$n" ] || [ -e "/etc/systemd/system/$n.service" ]; then
    echo "NOTE: files of the old '$n' installation still exist (/opt/$n, /var/lib/$n, /var/backups/$n, $n.service)."
    echo "      Remove them when you no longer need them: docs/upgrade.md, \"Cleanup after the rename\"."
  fi
done
