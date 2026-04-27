#!/bin/bash
# ============================================================
# OsTv Installer — master script
# ============================================================
# Встановлює OsTv на чистій Ubuntu 22.04/24.04 або Debian 12+.
#
# Usage:
#   # Інтерактивно з інтернету:
#   curl -fsSL https://your-host/install-ostv.sh | sudo bash
#
#   # З локального release tarball:
#   sudo bash install-ostv.sh --local ostv-release-v0.1.0.tar.gz
#
#   # Тільки певні етапи (для розробки):
#   sudo bash install-ostv.sh --skip-kiosk   # без переключення з GDM
#   sudo bash install-ostv.sh --rollback     # повернути GDM
#
# Вимоги:
#   - Root
#   - Ubuntu 22.04+ / Debian 12+
#   - ~2 ГБ вільно на диску (runtime+deps)
#   - Інтернет (для apt + pip + release archive)
# ============================================================

set -e

OSTV_VERSION="${OSTV_VERSION:-0.1.1}"
RELEASE_URL="${RELEASE_URL:-https://denromvas.website/ostv/ostv-release-v${OSTV_VERSION}.tar.gz}"
LOCAL_TARBALL=""
SKIP_KIOSK=0
ROLLBACK=0

# ---- Args ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --local) LOCAL_TARBALL="$2"; shift 2 ;;
        --skip-kiosk) SKIP_KIOSK=1; shift ;;
        --rollback) ROLLBACK=1; shift ;;
        --help|-h)
            sed -n '/^# ====/,/^# ====$/p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "!!! Run as root (sudo bash $0)"; exit 1
fi

# ---- Rollback path ----
if [ "$ROLLBACK" = "1" ]; then
    echo "=== OsTv → GDM rollback ==="
    systemctl disable --now ostv-brain.service 2>/dev/null || true
    rm -f /etc/systemd/system/ostv-brain.service
    rm -rf /etc/systemd/system/getty@tty1.service.d
    systemctl enable gdm.service 2>/dev/null || systemctl enable lightdm.service 2>/dev/null || true
    systemctl set-default graphical.target
    systemctl daemon-reload
    echo "Rollback complete. sudo reboot"
    exit 0
fi

# ---- Pre-flight ----
echo "============================================================"
echo "  OsTv v${OSTV_VERSION} Installer"
echo "============================================================"
. /etc/os-release
echo "OS: ${PRETTY_NAME}"
if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]] && [[ "$ID_LIKE" != *ubuntu* ]] && [[ "$ID_LIKE" != *debian* ]]; then
    echo "!!! Підтримуються Ubuntu/Debian; отримано: $ID"
    echo "Продовжити однак? (y/N)"
    read -r ok
    [[ "$ok" =~ ^[Yy] ]] || exit 1
fi

WORKDIR=$(mktemp -d -t ostv-install-XXXX)
trap "rm -rf $WORKDIR" EXIT

# ---- 1. Get release tarball ----
echo ""
echo "=== 1. Release artifact ==="
if [ -n "$LOCAL_TARBALL" ]; then
    [ -f "$LOCAL_TARBALL" ] || { echo "!!! $LOCAL_TARBALL not found"; exit 1; }
    cp "$LOCAL_TARBALL" "$WORKDIR/release.tar.gz"
    echo "using local: $LOCAL_TARBALL"
else
    echo "downloading $RELEASE_URL..."
    curl -fL --progress-bar -o "$WORKDIR/release.tar.gz" "$RELEASE_URL"
fi
tar -xzf "$WORKDIR/release.tar.gz" -C "$WORKDIR"
RELEASE_ROOT="$WORKDIR/release"
[ -d "$RELEASE_ROOT" ] || { echo "!!! bad tarball"; exit 1; }
ls "$RELEASE_ROOT"

# ---- 2. System packages ----
echo ""
echo "=== 2. APT packages ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update 2>&1 | tail -3 || true
apt-get install -y \
    mpv yt-dlp ffmpeg \
    python3-venv python3-pip python3-evdev \
    openbox xinit xserver-xorg xterm \
    libwebkit2gtk-4.1-0 libayatana-appindicator3-1 librsvg2-2 libxdo3 \
    pipewire pipewire-pulse wireplumber alsa-utils pulseaudio-utils \
    wmctrl xdotool \
    git jq curl wget \
    2>&1 | tail -5

# ---- 3. Users ----
echo ""
echo "=== 3. Users ==="
if ! id ostv >/dev/null 2>&1; then
    useradd --system --gid nogroup --home /var/lib/ostv --shell /usr/sbin/nologin \
            --comment "OsTv daemon" ostv
fi
getent group ostv >/dev/null || groupadd --system ostv
usermod -g ostv ostv 2>/dev/null || true

if ! id tv >/dev/null 2>&1; then
    useradd --uid 1500 --create-home --shell /bin/bash \
            --comment "OsTv kiosk" tv
fi
usermod -aG ostv,video,audio,input,render tv 2>/dev/null || true
passwd -d tv

# ---- 4. Layout ----
echo ""
echo "=== 4. Layout /opt/ostv ==="
mkdir -p /opt/ostv/{bin,brain,ui,apps,parsers,shared,scripts}
mkdir -p /etc/ostv /var/log/ostv /var/lib/ostv/pending

# version pin (для update.sh порівняння)
echo "$OSTV_VERSION" > /etc/ostv/version

cat > /usr/lib/tmpfiles.d/ostv.conf <<EOF
d /run/ostv 0775 root ostv -
d /run/ostv/sockets 0775 root ostv -
EOF
systemd-tmpfiles --create /usr/lib/tmpfiles.d/ostv.conf || true

# ---- 5. Copy release content ----
echo ""
echo "=== 5. Deploy files ==="
cp -r "$RELEASE_ROOT/brain/"* /opt/ostv/brain/
cp -r "$RELEASE_ROOT/parsers/"* /opt/ostv/parsers/
cp -r "$RELEASE_ROOT/bin/"* /opt/ostv/bin/
cp "$RELEASE_ROOT/mpv.input.conf" /opt/ostv/mpv.input.conf 2>/dev/null || true

# updater
if [ -f "$RELEASE_ROOT/update.sh" ]; then
    cp "$RELEASE_ROOT/update.sh" /opt/ostv/scripts/update.sh
    chmod 0755 /opt/ostv/scripts/update.sh
    chown root:root /opt/ostv/scripts/update.sh
fi

[ -f /etc/ostv/config.toml ] || cp "$RELEASE_ROOT/config/config.toml" /etc/ostv/config.toml 2>/dev/null || true
[ -f /etc/ostv/secrets.env ] || cat > /etc/ostv/secrets.env <<EOF
# OsTv secrets. chmod 0600. Вставте Claude/Anthropic API key тут:
# ANTHROPIC_API_KEY=sk-ant-...
EOF
chmod 0600 /etc/ostv/secrets.env
chown root:ostv /etc/ostv/secrets.env

chmod +x /opt/ostv/bin/ostv-ui /opt/ostv/bin/brain.sh 2>/dev/null || true
chmod +x /opt/ostv/parsers/*/parser.py /opt/ostv/parsers/*/*.py 2>/dev/null || true

chown -R ostv:ostv /opt/ostv /var/log/ostv /var/lib/ostv
chmod 0775 /opt/ostv /var/log/ostv /var/lib/ostv
find /opt/ostv -type d -exec chmod g+s {} \;

# ---- 6. Python venv ----
echo ""
echo "=== 6. Python venv + dependencies ==="
if [ ! -f /opt/ostv/venv/bin/python ]; then
    python3 -m venv /opt/ostv/venv
fi
/opt/ostv/venv/bin/pip install --upgrade pip -q
/opt/ostv/venv/bin/pip install -q \
    anthropic \
    HdRezkaApi \
    yt-dlp \
    requests beautifulsoup4 \
    2>&1 | tail -3
chown -R ostv:ostv /opt/ostv/venv

# ---- 6.5. sudoers: tv NOPASSWD power ----
echo ""
echo "=== 6.5. sudoers rule for power commands ==="
cat > /etc/sudoers.d/ostv <<'EOF'
# OsTv Brain — tv user NOPASSWD on power management + updater
tv ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/bin/systemctl suspend, /usr/bin/systemctl halt
tv ALL=(root) NOPASSWD: /opt/ostv/scripts/update.sh
EOF
chmod 0440 /etc/sudoers.d/ostv
visudo -c -f /etc/sudoers.d/ostv || { echo "!!! bad sudoers"; rm /etc/sudoers.d/ostv; exit 1; }

# ---- 7. Brain systemd ----
echo ""
echo "=== 7. systemd: ostv-brain.service ==="
cat > /etc/systemd/system/ostv-brain.service <<'EOF'
[Unit]
Description=OsTv Brain Daemon
After=network.target sound.target

[Service]
Type=simple
User=tv
Group=ostv
EnvironmentFile=-/etc/ostv/secrets.env
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/1500
RuntimeDirectory=ostv
RuntimeDirectoryMode=0775
ExecStart=/opt/ostv/venv/bin/python /opt/ostv/brain/brain.py
Restart=on-failure
RestartSec=3
StandardOutput=append:/var/log/ostv/brain.log
StandardError=append:/var/log/ostv/brain.err.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ostv-brain.service

# ---- 8. Kiosk session (optional) ----
if [ "$SKIP_KIOSK" = "0" ]; then
    echo ""
    echo "=== 8. Kiosk session (getty+openbox+ostv-ui) ==="

    # .xinitrc
    cat > /home/tv/.xinitrc <<'XI'
#!/bin/sh
set +e
mkdir -p /home/tv/.local/share/ostv
exec >/home/tv/.local/share/ostv/xsession.log 2>&1
echo "=== $(date) OsTv session start ==="

export XDG_CURRENT_DESKTOP=kiosk DESKTOP_SESSION=kiosk
unset GNOME_SHELL_SESSION_MODE GIO_LAUNCHED_DESKTOP_FILE

# nouveau/software-render workaround (на GPU з hardware GL — можна прибрати)
export GDK_DEBUG=gl-disable
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_LOADER_DRIVER_OVERRIDE=llvmpipe

xset s off -dpms s noblank
setxkbmap -layout us,ua -option "grp:alt_shift_toggle,grp_led:scroll"

# Kill вбудовані GNOME/Ubuntu autostart bloat що могли прослизнути
(sleep 2 && pkill -u tv -9 firefox update-notifier nm-applet touchegg \
    fluidsynth evolution-alarm geoclue 2>/dev/null) &

# UI (Brain вже стартує через systemd)
/opt/ostv/bin/ostv-ui &
(sleep 4 && wmctrl -r OsTv -b add,fullscreen && wmctrl -a OsTv) &

exec openbox-session
XI
    chown tv:tv /home/tv/.xinitrc
    chmod +x /home/tv/.xinitrc

    # log dir для xsession.log + startx.err (інакше exec startx падає bash з No such file)
    mkdir -p /home/tv/.local/share/ostv
    chown -R tv:tv /home/tv/.local

    # .bash_profile autostart X
    cat > /home/tv/.bash_profile <<'BP'
if [[ -z $DISPLAY ]] && [[ $(tty) = /dev/tty1 ]]; then
    mkdir -p /home/tv/.local/share/ostv
    exec startx 2>/home/tv/.local/share/ostv/startx.err
fi
BP
    chown tv:tv /home/tv/.bash_profile

    # Openbox
    mkdir -p /home/tv/.config/openbox
    cat > /home/tv/.config/openbox/rc.xml <<'OB'
<?xml version="1.0"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <applications>
    <application name="ostv-ui"><fullscreen>yes</fullscreen><decor>no</decor></application>
  </applications>
</openbox_config>
OB
    chown -R tv:tv /home/tv/.config

    # getty autologin
    mkdir -p /etc/systemd/system/getty@tty1.service.d
    cat > /etc/systemd/system/getty@tty1.service.d/override.conf <<'GT'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin tv --noclear %I $TERM
GT

    # Disable GDM/LightDM
    systemctl disable gdm.service 2>/dev/null || true
    systemctl disable lightdm.service 2>/dev/null || true
    systemctl set-default multi-user.target
    systemctl daemon-reload

    # Clear autostart bloat
    for f in /etc/xdg/autostart/firefox*.desktop \
             /etc/xdg/autostart/update-notifier.desktop \
             /etc/xdg/autostart/nm-applet.desktop \
             /etc/xdg/autostart/touchegg.desktop \
             /etc/xdg/autostart/deja-dup-monitor.desktop \
             /etc/xdg/autostart/evolution-alarm-notify.desktop \
             /etc/xdg/autostart/gnome-*.desktop \
             /etc/xdg/autostart/ubuntu-*.desktop \
             /etc/xdg/autostart/org.gnome.SettingsDaemon.*.desktop
    do
        [ -f "$f" ] && mv "$f" "${f}.disabled"
    done
    rm -rf /home/tv/.config/autostart/* 2>/dev/null || true
fi

# ---- 9. Start Brain ----
echo ""
echo "=== 9. Starting ostv-brain.service ==="
systemctl restart ostv-brain.service
sleep 2
systemctl is-active ostv-brain.service

# ---- 10. Done ----
echo ""
echo "============================================================"
echo "  OsTv v${OSTV_VERSION} installed!"
echo "============================================================"
echo ""
echo "  Reboot щоб запустити kiosk:"
echo "    sudo reboot"
echo ""
echo "  Вставити Claude API key / OAuth login:"
echo "    echo 'ANTHROPIC_API_KEY=sk-ant-...' | sudo tee -a /etc/ostv/secrets.env"
echo "    # АБО"
echo "    sudo -u tv claude  # login via OAuth (claude.ai account)"
echo ""
echo "  Rollback до GDM+GNOME:"
echo "    sudo bash $(realpath "$0") --rollback"
echo ""
