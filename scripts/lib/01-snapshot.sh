#!/bin/bash
# 01-snapshot.sh
# Знімає snapshot поточного стану системи в /var/backups/ostv-snapshot-<timestamp>/.
# Корисно для порівняння "до/після" установки OsTv та для rollback.
#
# Usage: sudo bash 01-snapshot.sh

set +e

SNAPSHOT_DIR=/var/backups/ostv-snapshot-$(date +%Y%m%d-%H%M)
mkdir -p "$SNAPSHOT_DIR"
echo "=== Snapshot dir: $SNAPSHOT_DIR ==="

echo "--- OS info ---"
{
    echo "=== lsb_release ==="
    lsb_release -a 2>&1
    echo
    echo "=== uname ==="
    uname -a
    echo
    echo "=== /etc/os-release ==="
    cat /etc/os-release
} > "$SNAPSHOT_DIR/os-info.txt"

echo "--- Installed packages ---"
dpkg-query -W -f='${Package}\t${Version}\n' > "$SNAPSHOT_DIR/packages.tsv"
echo "  $(wc -l < "$SNAPSHOT_DIR/packages.tsv") packages"

echo "--- apt sources ---"
mkdir -p "$SNAPSHOT_DIR/apt"
cp /etc/apt/sources.list "$SNAPSHOT_DIR/apt/" 2>/dev/null
cp -r /etc/apt/sources.list.d "$SNAPSHOT_DIR/apt/" 2>/dev/null

echo "--- systemd units ---"
systemctl list-unit-files --no-pager > "$SNAPSHOT_DIR/systemd-unit-files.txt"
systemctl list-units --all --no-pager > "$SNAPSHOT_DIR/systemd-units-all.txt"
systemctl list-units --type=service --state=running --no-pager > "$SNAPSHOT_DIR/systemd-running.txt"
systemctl get-default > "$SNAPSHOT_DIR/systemd-default-target.txt"

echo "--- Display manager ---"
{
    echo "default-display-manager:"
    cat /etc/X11/default-display-manager 2>/dev/null || echo "none"
    echo
    echo "GDM auto-login:"
    grep -E "^Automatic" /etc/gdm3/custom.conf 2>/dev/null || echo "not configured"
    echo
    echo "LightDM auto-login:"
    grep -rh "^autologin" /etc/lightdm/ 2>/dev/null || echo "not configured"
} > "$SNAPSHOT_DIR/display-manager.txt"

echo "--- Users ---"
getent passwd | awk -F: '$3 >= 1000 && $3 < 65000' > "$SNAPSHOT_DIR/users.txt"

echo "--- Network ---"
{
    ip -br addr
    echo
    ip route
    echo
    cat /etc/hostname
} > "$SNAPSHOT_DIR/network.txt"

echo "--- Disk layout ---"
{
    df -h
    echo
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE
} > "$SNAPSHOT_DIR/disk.txt"

echo "--- GPU ---"
{
    lspci -k | grep -A 3 -iE "VGA|3D"
    echo
    which nvidia-smi && nvidia-smi 2>/dev/null || echo "no nvidia-smi"
    echo
    which vdpauinfo && vdpauinfo 2>/dev/null | head -30 || echo "no vdpauinfo"
    echo
    which vainfo && vainfo 2>/dev/null | head -30 || echo "no vainfo"
} > "$SNAPSHOT_DIR/gpu.txt"

echo "--- Autostart / .desktop ---"
ls /etc/xdg/autostart/ > "$SNAPSHOT_DIR/autostart-system.txt" 2>/dev/null
ls /home/*/\.config/autostart/ > "$SNAPSHOT_DIR/autostart-users.txt" 2>/dev/null

echo
echo "=== Snapshot saved to: $SNAPSHOT_DIR ==="
du -sh "$SNAPSHOT_DIR"
