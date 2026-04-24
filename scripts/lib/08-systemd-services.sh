#!/bin/bash
# 08-systemd-services.sh
# Встановлює systemd unit для ostv-brain.service (system-level).
# Тепер Brain автостартує при boot, перезапускається при падінні,
# а .xinitrc лише стартує UI (Brain уже слухає socket).
#
# Usage: sudo bash 08-systemd-services.sh

set -e

echo "=== Create ostv-brain.service ==="
cat > /etc/systemd/system/ostv-brain.service <<'SVC'
[Unit]
Description=OsTv Brain Daemon
After=network.target sound.target
Wants=network.target

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
SVC

echo "=== Remove Brain from .xinitrc (тепер — systemd) ==="
# Замінюємо в .xinitrc блок запуску Brain на порожнє — тепер systemd
if grep -q "brain/brain.py" /home/tv/.xinitrc; then
    sed -i '/# Brain$/,+3 d' /home/tv/.xinitrc
    # Альтернативно — простіше: прибираємо конкретний запуск
    sed -i '/brain\.py/d' /home/tv/.xinitrc
    sed -i '/brain pid/d' /home/tv/.xinitrc
fi

echo "=== Enable + start ==="
systemctl daemon-reload
systemctl enable ostv-brain.service
systemctl restart ostv-brain.service
sleep 2

echo "=== Status ==="
systemctl status ostv-brain.service --no-pager | head -15
echo
ls -la /run/ostv/brain.sock 2>&1

echo
echo "=== Done ==="
