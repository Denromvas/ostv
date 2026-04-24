#!/bin/bash
# brain.sh — bash wrapper для JSON-RPC викликів до Brain.
#
# Usage:
#   brain.sh <method> [json_params]
#
# Examples:
#   brain.sh ping
#   brain.sh search_all '{"query":"Матриця","limit":5}'
#   brain.sh play_url '{"url":"https://..."}'

set -e

METHOD="${1:?method required. Usage: brain.sh <method> [json_params]}"
PARAMS="$2"
[ -z "$PARAMS" ] && PARAMS='{}'
SOCKET="/run/ostv/brain.sock"

if [ ! -S "$SOCKET" ]; then
    echo "{\"error\":\"brain socket not found: $SOCKET\"}" >&2
    exit 1
fi

# Python надійніше ніж nc (nc -q завершує connection до того як readline відпрацює)
exec python3 - "$METHOD" "$PARAMS" "$SOCKET" <<'PY'
import json, socket, sys
method, params_str, sock_path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    params = json.loads(params_str) if params_str.strip() else {}
except json.JSONDecodeError as e:
    print(json.dumps({"error": f"bad params JSON: {e}"}))
    sys.exit(2)

req = {"method": method, "params": params, "id": 1}
s = socket.socket(socket.AF_UNIX)
s.connect(sock_path)
s.sendall((json.dumps(req) + "\n").encode())
# receive line
buf = b""
while b"\n" not in buf:
    chunk = s.recv(4096)
    if not chunk:
        break
    buf += chunk
s.close()
line = buf.split(b"\n", 1)[0]
print(line.decode())
PY
