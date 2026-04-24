#!/bin/bash
# 07-kiosk-setup.sh
# Переключає машину з GDM+GNOME на OsTv kiosk:
#   - Xorg + openbox для юзера `tv`
#   - Brain як systemd user service (tv)
#   - Tauri UI старт через ~/.xinitrc
#   - Autologin `tv` на tty1 (getty), GDM вимкнений
#
# Rollback: див. 07-kiosk-rollback.sh
#
# Usage: sudo bash 07-kiosk-setup.sh

set -e

echo "=== Install openbox + xinit ==="
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    openbox xinit xserver-xorg xterm 2>&1 | tail -3

echo "=== Copy ostv-ui binary to /opt/ostv/bin ==="
mkdir -p /opt/ostv/bin
if [ -f /tmp/ostv-ui/src-tauri/target/release/ostv-ui ]; then
    cp /tmp/ostv-ui/src-tauri/target/release/ostv-ui /opt/ostv/bin/ostv-ui
    chown ostv:ostv /opt/ostv/bin/ostv-ui
    chmod 0755 /opt/ostv/bin/ostv-ui
    echo "binary copied"
else
    echo "!!! build Tauri first: cd /tmp/ostv-ui && npm run tauri build"
    exit 1
fi

echo "=== Symlinked resources Tauri requires ==="
# Tauri runtime files шукає поруч із bіnary — переконаємось що dist/ є.
# У debug mode inline. Для release вбудовано в binary.

echo "=== Create ~/.xinitrc for user tv ==="
cat > /home/tv/.xinitrc <<'XINITRC'
#!/bin/sh
# OsTv Xsession — openbox + brain + ostv-ui
set +e

# Log startup
mkdir -p /home/tv/.local/share/ostv
exec >/home/tv/.local/share/ostv/xsession.log 2>&1
echo "=== $(date) OsTv session start ==="

# Disable screen blanking / DPMS (TV завжди працює)
xset s off
xset -dpms
xset s noblank

# Set keyboard layouts
setxkbmap -layout us,ua -option "grp:alt_shift_toggle,grp_led:scroll"

# Start Brain у фоні
/opt/ostv/venv/bin/python /opt/ostv/brain/brain.py &
BRAIN_PID=$!
echo "brain pid=$BRAIN_PID"
sleep 1

# Tauri + nouveau — software render (без цього чорний екран)
export GDK_DEBUG=gl-disable
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_LOADER_DRIVER_OVERRIDE=llvmpipe

# Start Tauri UI fullscreen
/opt/ostv/bin/ostv-ui &
UI_PID=$!
echo "ui pid=$UI_PID"

# WM — openbox в foreground, stops коли user виходить
exec openbox-session
XINITRC
chown tv:tv /home/tv/.xinitrc
chmod +x /home/tv/.xinitrc

echo "=== Create ~/.bash_profile for user tv (auto-startx on tty1) ==="
cat > /home/tv/.bash_profile <<'BASHPROFILE'
# OsTv auto-start X on tty1
if [[ -z $DISPLAY ]] && [[ $(tty) = /dev/tty1 ]]; then
    exec startx 2>/home/tv/.local/share/ostv/startx.err
fi
BASHPROFILE
chown tv:tv /home/tv/.bash_profile

echo "=== Configure getty@tty1 autologin ==="
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/override.conf <<'GETTY'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin tv --noclear %I $TERM
GETTY

echo "=== Create openbox config dir + minimal rc.xml ==="
mkdir -p /home/tv/.config/openbox
cat > /home/tv/.config/openbox/rc.xml <<'OBRC'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance><strength>10</strength><screen_edge_strength>20</screen_edge_strength></resistance>
  <focus>
    <focusNew>yes</focusNew>
    <followMouse>no</followMouse>
    <underMouse>no</underMouse>
  </focus>
  <placement><policy>Smart</policy><center>yes</center></placement>
  <theme><name>Clearlooks</name><keepBorder>no</keepBorder></theme>
  <desktops><number>1</number></desktops>
  <resize><drawContents>yes</drawContents></resize>
  <applications>
    <application name="ostv-ui">
      <fullscreen>yes</fullscreen>
      <decor>no</decor>
      <layer>normal</layer>
    </application>
  </applications>
</openbox_config>
OBRC
chown -R tv:tv /home/tv/.config

echo "=== Disable GDM, set default target = multi-user ==="
systemctl disable gdm.service
systemctl set-default multi-user.target

echo "=== Reload systemd ==="
systemctl daemon-reload

echo
echo "=== DONE ==="
echo "Що далі:"
echo "  sudo reboot   → машина стартує напряму в OsTv kiosk"
echo ""
echo "Якщо щось піде не так — SSH в машину і:"
echo "  sudo bash 07-kiosk-rollback.sh"
