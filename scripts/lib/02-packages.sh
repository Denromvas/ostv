#!/bin/bash
# 02-packages.sh
# Встановлює базові пакети для OsTv runtime.
# Ідемпотентний: apt пропускає те що вже стоїть.
#
# Usage: sudo bash 02-packages.sh

set +e  # толеруємо зламані 3rd-party репо (GamePack має багато з expired GPG keys)

echo "=== apt update (broken 3rd-party repos ignored) ==="
apt-get update 2>&1 | tail -15 || echo "W: some repos failed, continuing with cache"
echo "---"

echo "=== Install OsTv base packages ==="

# Медіа
MEDIA_PKGS=(
    mpv              # плеєр
    vainfo           # діагностика VA-API
    vdpauinfo        # діагностика VDPAU
    libvdpau1        # VDPAU runtime
    mesa-vdpau-drivers  # VDPAU для nouveau/radeon/Intel (обмежено)
    pipewire
    pipewire-pulse
    wireplumber
    alsa-utils
)

# Контейнери
CONTAINER_PKGS=(
    docker.io
    docker-compose-v2  # може бути docker-compose у старих Ubuntu
)

# Графіка та композитор (для OsTv UI kiosk-сеансу)
GRAPHICS_PKGS=(
    weston
    cage             # wlroots kiosk compositor (легше за Weston)
    foot             # Wayland-термінал (Textual всередині працює)
    # greetd          # недоступний у Ubuntu 22.04 repos. Використовуємо getty autologin замість DM.
    fonts-jetbrains-mono
    fonts-noto-color-emoji
)

# Python і інструменти розробки
DEV_PKGS=(
    python3-venv
    python3-pip
    python3-evdev    # читання пульта
    git
    build-essential
    jq
    curl
    wget
)

# Встановлюємо одним batch-ом щоб apt мав змогу resolver раз
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    "${MEDIA_PKGS[@]}" \
    "${CONTAINER_PKGS[@]}" \
    "${GRAPHICS_PKGS[@]}" \
    "${DEV_PKGS[@]}" \
    || {
        echo "!!! Батч-установка впала. Спробуємо по одному пакету для діагностики."
        for pkg in "${MEDIA_PKGS[@]}" "${CONTAINER_PKGS[@]}" "${GRAPHICS_PKGS[@]}" "${DEV_PKGS[@]}"; do
            DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" 2>&1 | tail -2 | sed "s|^|[$pkg] |"
        done
    }

echo "=== yt-dlp (через pip, щоб мати свіжу версію) ==="
if ! command -v yt-dlp >/dev/null 2>&1; then
    pip3 install --break-system-packages yt-dlp 2>/dev/null || pip3 install yt-dlp
fi
yt-dlp --version 2>/dev/null || echo "!!! yt-dlp install failed"

echo "=== Docker group — додати dromanyuk щоб не вимагало sudo ==="
usermod -aG docker dromanyuk

echo "=== Enable docker.service (не старт поки — стартанемо на 04-) ==="
systemctl enable docker.service

echo "=== Версії ==="
echo "docker:      $(docker --version 2>&1)"
echo "cage:        $(cage --version 2>&1 | head -1 || echo not-installed)"
echo "greetd:      $(dpkg -s greetd 2>/dev/null | grep Version || echo not-installed)"
echo "weston:      $(weston --version 2>&1 | head -1 || echo not-installed)"
echo "foot:        $(foot --version 2>&1 | head -1 || echo not-installed)"
echo "mpv:         $(mpv --version 2>&1 | head -1)"
echo "yt-dlp:      $(yt-dlp --version 2>&1 | tail -1)"
echo "python3:     $(python3 --version)"
echo "pipewire:    $(pipewire --version 2>&1 | head -1 || echo not-installed)"

echo
echo "=== Done. ==="
