#!/bin/bash
# ============================================================
# OsTv Release Builder
# ============================================================
# Пакує все runtime в ostv-release-v<version>.tar.gz для
# подальшого деплою через install-ostv.sh --local.
#
# Usage:
#   bash build-release.sh [--version 0.1.0]
#
# Результат: ostv-release-v<ver>.tar.gz у CWD
#
# Перед запуском — треба мати:
#   1. Зібраний Tauri binary у /home/dromanyuk/ostv-ui/src-tauri/target/release/ostv-ui
#      (або бінар у /opt/ostv/bin/ostv-ui)
#   2. Brain sources в /mnt/e/OsTv/src/brain/ + parsers/ + bin/
# ============================================================

set -e

VERSION="${1:-0.1.0}"
if [[ "$1" == "--version" ]]; then VERSION="$2"; fi

OSTV_SRC="${OSTV_SRC:-/mnt/e/OsTv}"
TARGET_HOST="${TARGET_HOST:-192.168.88.29}"
TARGET_USER="${TARGET_USER:-dromanyuk}"

OUTDIR=$(mktemp -d -t ostv-build-XXXX)
RELEASE="$OUTDIR/release"
mkdir -p "$RELEASE"/{brain,bin,parsers/hdrezka,parsers/filmix,config}

echo "=== 1. Brain sources ==="
cp "$OSTV_SRC/src/brain/brain.py" "$RELEASE/brain/brain.py"

echo "=== 2. Parsers ==="
cp "$OSTV_SRC/src/parsers/hdrezka/hdrezka.py" "$RELEASE/parsers/hdrezka/"
cp "$OSTV_SRC/src/parsers/filmix/filmix.py" "$RELEASE/parsers/filmix/"

echo "=== 3. Bin scripts ==="
cp "$OSTV_SRC/src/bin/brain.sh" "$RELEASE/bin/brain.sh"

echo "=== 4. Tauri binary ==="
# Беремо бінар з цільової машини (там він зібраний) або локально якщо буде
TAURI_BIN=""
if [ -f "$OSTV_SRC/dist/ostv-ui" ]; then
    TAURI_BIN="$OSTV_SRC/dist/ostv-ui"
else
    echo "  pulling from $TARGET_USER@$TARGET_HOST..."
    scp "$TARGET_USER@$TARGET_HOST:/opt/ostv/bin/ostv-ui" "$RELEASE/bin/ostv-ui" 2>/dev/null || {
        echo "!!! Tauri binary не знайдений. Збери через:"
        echo "    ssh $TARGET_USER@$TARGET_HOST 'cd /home/dromanyuk/ostv-ui && npm run tauri build'"
        echo "    а потім: scp $TARGET_USER@$TARGET_HOST:/opt/ostv/bin/ostv-ui $OSTV_SRC/dist/ostv-ui"
        exit 1
    }
fi
[ -n "$TAURI_BIN" ] && cp "$TAURI_BIN" "$RELEASE/bin/ostv-ui"
chmod +x "$RELEASE/bin/ostv-ui"

echo "=== 5. Config placeholders ==="
cat > "$RELEASE/config/config.toml" <<EOF
# OsTv user configuration
[general]
lang = "uk"
theme = "dendy-classic"

[ai]
provider = "claude-cli"  # or anthropic-sdk
model = "claude-sonnet-4-5"
EOF

echo "=== 6. mpv input.conf ==="
cat > "$RELEASE/mpv.input.conf" <<EOF
ESC       quit
q         quit
CLOSE_WIN quit
MBTN_MID  quit
EOF

echo "=== 7. Install script + updater ==="
cp "$OSTV_SRC/scripts/install-ostv.sh" "$RELEASE/install.sh"
cp "$OSTV_SRC/scripts/update.sh"       "$RELEASE/update.sh"
chmod +x "$RELEASE/install.sh" "$RELEASE/update.sh"

echo "=== 8. Manifest ==="
cat > "$RELEASE/MANIFEST.txt" <<EOF
OsTv Release v$VERSION
Built: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Host:  $(hostname)

Files:
  brain/brain.py        — Brain daemon (Python asyncio)
  parsers/hdrezka/      — HDRezka parser (HdRezkaApi)
  parsers/filmix/       — Filmix parser (WIP)
  bin/ostv-ui           — Tauri 2 binary (prebuilt)
  bin/brain.sh          — Bash wrapper для Claude Bash tool
  mpv.input.conf        — mpv keybinds (ESC=quit)
  config/config.toml    — Default config
  install.sh            — Master installer

Install:
  sudo bash install.sh --local $(basename $(pwd))
EOF

echo "=== 9. Tar ==="
OUT="ostv-release-v${VERSION}.tar.gz"
tar -czf "$OUT" -C "$OUTDIR" release
ls -lh "$OUT"
rm -rf "$OUTDIR"

echo ""
echo "=== Done! ==="
echo ""
echo "Release: $(realpath $OUT)"
echo ""
echo "Install on fresh Ubuntu/Debian:"
echo "  scp $OUT user@target:/tmp/"
echo "  ssh user@target"
echo "  sudo bash install.sh --local /tmp/$OUT  # (розпакувати спочатку)"
echo ""
echo "  АБО:"
echo "  tar -xzf $OUT"
echo "  cd release"
echo "  sudo bash install.sh --local ../$OUT"
