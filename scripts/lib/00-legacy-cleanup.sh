#!/bin/bash
# 00-legacy-cleanup.sh
# Видалення legacy-сервісів що залишилися з попередніх експериментів
# на цільовій машині. Безпечно запускати повторно (ідемпотентно).
# Бекап сервісів і даних — у /var/backups/ostv-rollback-<timestamp>/.
#
# Usage: sudo bash 00-legacy-cleanup.sh

set +e

# Список unit-файлів для видалення (доповнювати при потребі)
LEGACY_UNITS=(
    cinema-assistant
    cinema-backend
    claude-assistant
    x11vnc
)

# Список директорій проектів для архівації та видалення
LEGACY_DIRS=(
    /home/dromanyuk/cinema_assistant
    /home/dromanyuk/claude-desktop-assistant
    /home/dromanyuk/.vnc
)

# Пакети які варто purge
LEGACY_APT_PKGS=(
    x11vnc
)

BACKUP_DIR=/var/backups/ostv-rollback-$(date +%Y%m%d-%H%M)
mkdir -p "$BACKUP_DIR/systemd" "$BACKUP_DIR/home"
echo "=== Backup dir: $BACKUP_DIR ==="

echo "--- 1. Backup unit files ---"
for svc in "${LEGACY_UNITS[@]}"; do
    if [ -f "/etc/systemd/system/$svc.service" ]; then
        cp "/etc/systemd/system/$svc.service" "$BACKUP_DIR/systemd/"
        echo "backed up $svc.service"
    fi
done

echo "--- 2. Tar project dirs ---"
for dir in "${LEGACY_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        name=$(basename "$dir" | tr "." "_")
        tar czf "$BACKUP_DIR/home/${name}.tar.gz" "$dir" 2>/dev/null
        echo "archived $dir -> ${name}.tar.gz ($(du -sh "$BACKUP_DIR/home/${name}.tar.gz" | cut -f1))"
    fi
done

echo "--- 3. Stop services ---"
systemctl stop "${LEGACY_UNITS[@]}" 2>&1 | head -10

echo "--- 4. Disable ---"
systemctl disable "${LEGACY_UNITS[@]}" 2>&1 | head -10

echo "--- 5. Remove unit files ---"
for svc in "${LEGACY_UNITS[@]}"; do
    rm -fv "/etc/systemd/system/$svc.service"
done

echo "--- 6. daemon-reload ---"
systemctl daemon-reload
systemctl reset-failed

echo "--- 7. Remove project dirs ---"
for dir in "${LEGACY_DIRS[@]}"; do
    rm -rf "$dir"
done
echo "removed"

echo "--- 8. apt purge legacy packages ---"
DEBIAN_FRONTEND=noninteractive apt-get -y remove --purge "${LEGACY_APT_PKGS[@]}" 2>&1 | tail -5

echo "--- 9. Verify ---"
systemctl list-units --type=service --state=running --no-pager 2>/dev/null \
    | grep -E "cinema|claude|x11vnc" \
    || echo "OK: no legacy services running"

echo
echo "=== Backup location: $BACKUP_DIR ==="
echo "=== If rollback needed: unpack tar.gz files, cp service files back, systemctl daemon-reload, systemctl enable <svc> ==="
