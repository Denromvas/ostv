#!/bin/bash
# 04-ostv-layout.sh
# Створює директорії та файли OsTv системного layout:
#   /opt/ostv/         — код Brain, UI, CLI модулів
#   /etc/ostv/         — конфіги
#   /var/log/ostv/     — логи
#   /run/ostv/         — UNIX-сокети (ephemeral)
#   /var/lib/ostv/     — persistent runtime state
#
# Ідемпотентний.
#
# Usage: sudo bash 04-ostv-layout.sh

set -e

echo "=== System dirs ==="
mkdir -p /opt/ostv/{brain,ui,apps,parsers,shared}
mkdir -p /etc/ostv
mkdir -p /var/log/ostv
mkdir -p /var/lib/ostv/pending
mkdir -p /usr/lib/tmpfiles.d

echo "=== Tmpfiles for /run/ostv (created on boot) ==="
cat > /usr/lib/tmpfiles.d/ostv.conf <<'EOF'
# OsTv runtime sockets and tmp dirs
d /run/ostv 0755 root ostv -
d /run/ostv/sockets 0775 root ostv -
EOF
# Trigger creation immediately
systemd-tmpfiles --create /usr/lib/tmpfiles.d/ostv.conf || true

echo "=== Create ostv group/user (system, for brain daemon) ==="
if ! getent group ostv >/dev/null; then
    groupadd --system ostv
fi
if ! id ostv >/dev/null 2>&1; then
    useradd --system --gid ostv --home /var/lib/ostv --shell /usr/sbin/nologin \
            --comment "OsTv brain daemon" ostv
fi
# tv юзер теж у групі ostv — може читати сокет
usermod -aG ostv tv 2>/dev/null || true

echo "=== Ownership ==="
chown -R ostv:ostv /opt/ostv /var/log/ostv /var/lib/ostv
chmod 0755 /opt/ostv /var/log/ostv /var/lib/ostv

echo "=== Default config (placeholder) ==="
if [ ! -f /etc/ostv/config.toml ]; then
    cat > /etc/ostv/config.toml <<'EOF'
# OsTv system configuration
# See /mnt/e/OsTv/docs/TZ.md §23 for full reference

[general]
lang = "uk"
theme = "dendy-classic"

[ai]
# Залишити порожнім — Brain працюватиме в "manual only" режимі
# без API ключа. Ключ кладеться в /etc/ostv/secrets.env з chmod 0600.
provider = "claude"
model = "claude-haiku-4-5"
max_tokens = 2048

[voice]
enabled = false

[remote]
usb_hid = true
EOF
fi

if [ ! -f /etc/ostv/secrets.env ]; then
    touch /etc/ostv/secrets.env
    chmod 0600 /etc/ostv/secrets.env
    chown root:ostv /etc/ostv/secrets.env
    cat > /etc/ostv/secrets.env <<'EOF'
# OsTv secrets — DO NOT COMMIT. Mode 0600, owner root:ostv.
# Приклади:
# CLAUDE_API_KEY=sk-ant-...
# GEMINI_API_KEY=AIza...
EOF
fi

echo "=== Layout ==="
find /opt/ostv /etc/ostv -maxdepth 2 -type d -o -type f 2>/dev/null | sort
echo
echo "=== Permissions ==="
ls -la /opt/ostv /etc/ostv /var/log/ostv /var/lib/ostv

echo "=== Done. ==="
