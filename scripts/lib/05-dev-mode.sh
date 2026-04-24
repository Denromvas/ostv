#!/bin/bash
# 05-dev-mode.sh
# Розслаблює permissions на /opt/ostv, /run/ostv, /var/log/ostv, /var/lib/ostv
# щоб user `dromanyuk` міг розробляти і запускати OsTv компоненти вручну.
# У production (systemd) — цей скрипт НЕ запускається, там окремий unit під
# user=ostv.
#
# Usage: sudo bash 05-dev-mode.sh

set -e

echo "=== Add dromanyuk to ostv group (for shared access) ==="
usermod -aG ostv dromanyuk
id dromanyuk

echo "=== /opt/ostv: group rwx ==="
chgrp -R ostv /opt/ostv
chmod -R g+rwX /opt/ostv
find /opt/ostv -type d -exec chmod g+s {} \;

echo "=== /var/log/ostv /var/lib/ostv: group rw ==="
chmod 0775 /var/log/ostv /var/lib/ostv
chmod g+s /var/log/ostv /var/lib/ostv

echo "=== Update /run/ostv tmpfiles to 0775 ==="
cat > /usr/lib/tmpfiles.d/ostv.conf <<'EOF'
# OsTv runtime sockets and tmp dirs
# 0775 to allow `ostv` group write (brain + UI + dev user)
d /run/ostv 0775 root ostv -
d /run/ostv/sockets 0775 root ostv -
EOF
systemd-tmpfiles --create /usr/lib/tmpfiles.d/ostv.conf

echo "=== Show permissions ==="
ls -la /run/ostv /opt/ostv /var/log/ostv /var/lib/ostv

echo "=== Done. dromanyuk must relogin (or use 'newgrp ostv') for group to take effect. ==="
