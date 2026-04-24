#!/bin/bash
# 07-kiosk-rollback.sh — повертає GDM+GNOME, вимикає kiosk autologin
# Usage: sudo bash 07-kiosk-rollback.sh

set +e

echo "=== Remove getty@tty1 autologin override ==="
rm -f /etc/systemd/system/getty@tty1.service.d/override.conf
rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null

echo "=== Re-enable GDM ==="
systemctl enable gdm.service
systemctl set-default graphical.target
systemctl daemon-reload

echo "=== Done. Reboot to return to GNOME ==="
echo "  sudo reboot"
