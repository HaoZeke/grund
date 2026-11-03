#!/usr/bin/env bash
# Show that a browser-supplied model key and endpoint never reach a Caddy log.
#
# Runs deploy/Caddyfile on unprivileged local ports with:
#   - /agent/* proxied to a stub that accepts and drops the connection (502),
#   - /api/*   proxied to a port nothing listens on (502, dial error),
# sends requests that carry a dummy X-Grund-LLM-Key and X-Grund-LLM-Base, and
# greps every log and every file Caddy wrote for them. A control run with the
# global "log default" block removed must leak, or the check proves nothing.
#
#   CADDY=/path/to/caddy deploy/check-caddy-logs.sh
set -euo pipefail

CADDY=${CADDY:-caddy}
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$work"' EXIT

key="dummy-key-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
base="https://dummy-base-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n').example/v1"
user=checker
pass=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
stub=$(free_port)
dead=$(free_port)

python3 - "$stub" <<'EOF' &
import socket, sys
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", int(sys.argv[1])))
server.listen()
while True:
    conn, _ = server.accept()
    conn.recv(65536)
    conn.close()
EOF

mkdir -p "$work/web"
echo '<!doctype html><title>grund</title>' > "$work/web/index.html"

# Local runs only: no system trust-store install and no admin endpoint. The
# rest of the file is the deploy file as committed.
prepare() {
	local out=$1 control=$2
	if [ "$control" = 1 ]; then
		awk '/^\tlog default \{/{skip=1} skip&&/^\t\}$/{skip=0; next} !skip' "$here/Caddyfile" > "$out.tmp"
	else
		cp "$here/Caddyfile" "$out.tmp"
	fi
	awk 'NR==1,/^\{$/{if ($0=="{") {print; print "\tskip_install_trust"; print "\tadmin off"; next}} {print}' "$out.tmp" > "$out"
	rm "$out.tmp"
}

run() {
	local name=$1 control=$2
	local dir="$work/$name"
	mkdir -p "$dir/data" "$dir/config"
	prepare "$dir/Caddyfile" "$control"
	local http https
	http=$(free_port)
	https=$(free_port)
	GRUND_HTTP_PORT=$http GRUND_HTTPS_PORT=$https GRUND_HOST=localhost GRUND_IP=127.0.0.1 \
	GRUND_AUTH_USER=$user GRUND_AUTH_HASH=$("$CADDY" hash-password --plaintext "$pass") \
	GRUND_AGENT_UPSTREAM=127.0.0.1:$stub GRUND_API_UPSTREAM=127.0.0.1:$dead GRUND_WEB_ROOT="$work/web" \
	XDG_DATA_HOME="$dir/data" XDG_CONFIG_HOME="$dir/config" \
		"$CADDY" run --config "$dir/Caddyfile" --adapter caddyfile > "$dir/stdout.log" 2> "$dir/stderr.log" &
	local pid=$!
	for _ in $(seq 50); do
		curl -sk -o /dev/null "https://localhost:$https/" && break
		sleep 0.2
	done
	local h=(-H "X-Grund-LLM-Key: $key" -H "X-Grund-LLM-Base: $base" -H "X-Grund-LLM-Model: dummy-model")
	{
		echo "agent (stub drops the connection): $(curl -sk -u "$user:$pass" -o /dev/null -w '%{http_code}' "${h[@]}" -H 'Content-Type: application/json' -d '{}' "https://localhost:$https/agent/extrapolate")"
		echo "api (nothing listening):           $(curl -sk -u "$user:$pass" -o /dev/null -w '%{http_code}' "${h[@]}" -d '{}' "https://localhost:$https/api/ask")"
		echo "static page:                       $(curl -sk -u "$user:$pass" -o /dev/null -w '%{http_code}' "${h[@]}" "https://localhost:$https/")"
		echo "plain http on the IP:              $(curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' "${h[@]}" "http://127.0.0.1:$http/agent/extrapolate")"
	} > "$dir/requests.txt"
	sleep 0.5
	kill "$pid"
	wait "$pid" 2>/dev/null || true
	echo "== $name"
	cat "$dir/requests.txt"
	echo "log lines: $(cat "$dir"/stdout.log "$dir"/stderr.log | wc -l), of which http.log.error: $(grep -c '"logger":"http.log.error' "$dir/stderr.log" || true)"
	python3 - "$dir/stderr.log" <<'EOF'
import json, sys
for line in open(sys.argv[1]):
    try:
        record = json.loads(line)
    except ValueError:
        continue
    headers = (record.get("request") or {}).get("headers")
    if headers is not None:
        print(f"  {record.get('logger')} {record.get('status', record.get('level'))}: headers logged {sorted(headers)}")
EOF
	local hits
	hits=$(grep -rlF -e "$key" -e "${base#https://}" "$dir" --exclude=Caddyfile --exclude=requests.txt || true)
	if [ -n "$hits" ]; then
		echo "key or base FOUND in: $(echo "$hits" | sed "s#$dir/##" | tr '\n' ' ')"
		grep -hF "$key" "$dir"/*.log | head -n 1 | cut -c1-300
		return 1
	fi
	echo "key or base found in: nothing (searched $(find "$dir" -type f | wc -l) files)"
}

status=0
run deploy 0 || status=1
if run control-without-global-filter 1; then
	echo "control did not leak: the check cannot see the error log"
	status=1
else
	echo "control leaked as expected"
fi
exit $status
