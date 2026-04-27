#!/bin/bash
# ============================================================
#  OsTv updater — тягне latest release з GitHub і ставить
#  ============================================================
#  Виклик: sudo /opt/ostv/scripts/update.sh [--check] [--force]
#    --check  — тільки перевіряє, нічого не ставить
#    --force  — ставить навіть якщо така ж версія
#  Запускається через NOPASSWD-sudoers від юзера tv (Brain).
# ============================================================
set -euo pipefail

REPO="Denromvas/ostv"
API="https://api.github.com/repos/$REPO/releases/latest"
TMP="/tmp/ostv-update"
VER_FILE="/etc/ostv/version"
LOG="/var/log/ostv-update.log"

mkdir -p "$TMP"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date) update.sh start ==="

CHECK_ONLY=0
FORCE=0
for a in "$@"; do
    case "$a" in
        --check) CHECK_ONLY=1 ;;
        --force) FORCE=1 ;;
    esac
done

CURRENT="unknown"
[ -f "$VER_FILE" ] && CURRENT=$(cat "$VER_FILE")

# 1. fetch latest release info
JSON=$(curl -fsSL --max-time 20 "$API")
LATEST=$(echo "$JSON" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["tag_name"])')
TARBALL_URL=$(echo "$JSON" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for a in d.get("assets", []):
    if a["name"].endswith(".tar.gz"):
        print(a["browser_download_url"]); break
')

if [ -z "${LATEST:-}" ] || [ -z "${TARBALL_URL:-}" ]; then
    echo "ERROR: не зміг розпарсити GitHub API"
    echo '{"ok":false,"error":"github api parse"}'
    exit 1
fi

echo "current=$CURRENT  latest=$LATEST  asset=$TARBALL_URL"

# Нормалізація: tag_name = "v0.1.1", $CURRENT = "0.1.1" → порівнюємо без 'v'
LATEST_BARE="${LATEST#v}"

if [ "$CHECK_ONLY" = "1" ]; then
    HAS_UPDATE="false"
    [ "$LATEST_BARE" != "$CURRENT" ] && HAS_UPDATE="true"
    echo "{\"ok\":true,\"current\":\"$CURRENT\",\"latest\":\"$LATEST_BARE\",\"has_update\":$HAS_UPDATE}"
    exit 0
fi

if [ "$FORCE" != "1" ] && [ "$LATEST_BARE" = "$CURRENT" ]; then
    echo "Already at latest ($CURRENT)"
    echo "{\"ok\":true,\"already_latest\":true,\"current\":\"$CURRENT\"}"
    exit 0
fi

# 2. download
TARBALL="$TMP/$(basename "$TARBALL_URL")"
echo "downloading $TARBALL_URL → $TARBALL"
curl -fsSL --max-time 120 "$TARBALL_URL" -o "$TARBALL"
[ ! -s "$TARBALL" ] && { echo "ERROR: empty tarball"; exit 2; }

# 3. extract install.sh
WORK="$TMP/extract"
rm -rf "$WORK"
mkdir -p "$WORK"
tar -xzf "$TARBALL" -C "$WORK"
INSTALLER="$WORK/release/install.sh"
[ ! -f "$INSTALLER" ] && { echo "ERROR: install.sh не знайдено в архіві"; exit 3; }

# 4. run installer (idempotent — перетирає файли + перезапускає сервіси)
echo "running installer (skip-kiosk, kiosk вже налаштований)"
bash "$INSTALLER" --local "$TARBALL" --skip-kiosk

# 5. update version file
echo "$LATEST_BARE" > "$VER_FILE"

# 6. trigger UI reload (через brain.sh з юзера tv) — щоб новий бінарник підхопився
sudo -u tv -E /opt/ostv/bin/brain.sh reload_ui '{"hard":true}' 2>/dev/null || \
    echo "(reload_ui не вдався — UI оновиться при наступному ребуті)"

echo "=== $(date) update.sh done → $LATEST_BARE ==="
echo "{\"ok\":true,\"updated_to\":\"$LATEST_BARE\",\"from\":\"$CURRENT\"}"
