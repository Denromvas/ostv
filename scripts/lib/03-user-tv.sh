#!/bin/bash
# 03-user-tv.sh
# Створює kiosk-юзера `tv` для OsTv runtime.
# Ідемпотентний.
#
# Usage: sudo bash 03-user-tv.sh

set -e

TV_USER="tv"
TV_UID=1500
TV_GID=1500

echo "=== Create tv group/user ==="
if ! getent group "$TV_USER" >/dev/null; then
    groupadd --gid "$TV_GID" "$TV_USER"
    echo "group tv created (gid=$TV_GID)"
else
    echo "group tv exists"
fi

if ! id "$TV_USER" >/dev/null 2>&1; then
    useradd --uid "$TV_UID" --gid "$TV_GID" --create-home --shell /bin/bash \
            --comment "OsTv kiosk user" "$TV_USER"
    echo "user tv created (uid=$TV_UID)"
else
    echo "user tv exists"
fi

echo "=== Set empty password (kiosk mode) ==="
# Без пароля на локальний логін, але без sudo.
passwd -d "$TV_USER"

echo "=== Groups — додати до потрібних для Wayland/mpv/remote ==="
# video, audio — доступ до GPU/ALSA
# input — читати evdev для пульта
# render — DRM render nodes (для Wayland)
for grp in video audio input render plugdev; do
    if getent group "$grp" >/dev/null; then
        usermod -aG "$grp" "$TV_USER"
    fi
done
id "$TV_USER"

echo "=== User dirs ==="
sudo -u "$TV_USER" mkdir -p \
    /home/"$TV_USER"/.config/ostv \
    /home/"$TV_USER"/.local/bin \
    /home/"$TV_USER"/.local/share/ostv \
    /home/"$TV_USER"/media
ls -la /home/"$TV_USER"/

echo "=== Done. User tv ready. ==="
