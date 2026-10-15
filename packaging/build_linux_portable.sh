#!/usr/bin/env bash
# Self-contained Linux x86-64 distribution that runs on virtually any glibc distro (glibc >= 2.17):
# relocatable CPython from astral-sh/python-build-standalone + manylinux wheels. No Python/Node/SQLite needed
# on the target. Preferred over the PyInstaller build for servers (PyInstaller inherits the build host's glibc).
# Usage (repo root): bash packaging/build_linux_portable.sh  -> dist/PennyWarden-linux-x64-portable.tar.gz
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PBS_TAG="${PBS_TAG:-20251014}"
PYVER="${PYVER:-3.12.12}"
NAME="PennyWarden-linux-x64"
OUT="$ROOT/dist/portable/$NAME"
CACHE="$ROOT/build/cache"
ARCHIVE="cpython-${PYVER}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${ARCHIVE}"

test -f "$ROOT/backend/fmpoc/static/index.html" || { echo "Build the frontend first: npm --prefix frontend ci && npm --prefix frontend run build"; exit 1; }
rm -rf "$OUT"; mkdir -p "$OUT/app" "$CACHE/wheels-linux"
[ -f "$CACHE/$ARCHIVE" ] || { curl -fsSL -o "$CACHE/$ARCHIVE.part" "$URL"; mv "$CACHE/$ARCHIVE.part" "$CACHE/$ARCHIVE"; }
tar -xzf "$CACHE/$ARCHIVE" -C "$OUT"                       # -> $OUT/python/bin/python3
"$OUT/python/bin/python3" -m pip install --quiet --no-cache-dir --no-compile --only-binary=:all: \
   --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
   --python-version 3.12 --implementation cp --target "$OUT/python/lib/python3.12/site-packages" \
   -r "$ROOT/backend/requirements.txt"
cp -r "$ROOT/backend/fmpoc" "$OUT/app/fmpoc"
cp "$ROOT/LICENSE" "$ROOT/THIRD-PARTY-NOTICES.txt" "$OUT/"   # v1.5.0: AGPL-3.0 + third-party notices
cat > "$OUT/app/launch.py" <<'PY'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmpoc.__main__ import main
sys.exit(main())
PY
cat > "$OUT/pennywarden" <<'SH'
#!/bin/sh
# Self-contained launcher. Local mode by default; use --mode server for servers.
SELF="$0"   # 2.0.0 build 13: also works when started through a symlink to it
if [ -L "$SELF" ]; then SELF="$(readlink -f "$SELF" 2>/dev/null || echo "$SELF")"; fi
case "$SELF" in */*) HERE="${SELF%/*}" ;; *) HERE="." ;; esac
HERE="$(cd "$HERE" && pwd)"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$HERE/python/bin/python3" -I "$HERE/app/launch.py" "$@"
SH
chmod +x "$OUT/pennywarden"
# prune parts of the runtime the server never uses (tests, GUI toolkits, headers, pip)
L="$OUT/python/lib/python3.12"
rm -rf "$L/test" "$L/idlelib" "$L/tkinter" "$L/turtledemo" "$L/ensurepip" "$L/lib2to3" "$L/site-packages/pip" \
       "$L"/site-packages/pip-*.dist-info "$OUT/python/include" "$OUT/python/share" "$OUT"/python/lib/libtcl* \
       "$OUT"/python/lib/libtk* "$OUT"/python/lib/tcl* "$OUT"/python/lib/tk* "$L"/lib-dynload/_tkinter*
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
# strip debug symbols (python-build-standalone ships them; ~300 MB)
find "$OUT/python" -type f \( -name "*.so*" \) -exec strip --strip-debug {} + 2>/dev/null || true
tar -C "$ROOT/dist/portable" -czf "$ROOT/dist/$NAME-portable.tar.gz" "$NAME"
echo "Built $ROOT/dist/$NAME-portable.tar.gz"
