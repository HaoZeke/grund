#!/usr/bin/env bash
# Write the Caddy config for a Grund host and reload Caddy. Run on the host.
#
#   deploy/grund-vps-remote.sh IP [HOST]
#
# HOST defaults to the sslip.io name of IP, which gets a public certificate.
# The site on http://IP only redirects to https://HOST: nothing is proxied
# over plain http, so a model key typed into the UI never travels in
# cleartext. The Caddyfile is deploy/Caddyfile rendered with this host's
# values; the old one is kept as Caddyfile.bak-<time>. $GRUND_CADDY_DIR/Caddyfile
# (default /opt/grund) must be the file the Caddy container mounts as
# /etc/caddy/Caddyfile.
#
# Reads GRUND_AUTH_USER and GRUND_AUTH_HASH from /opt/grund/caddy.env
# (KEY=VALUE lines, chmod 600), and optional GRUND_*_UPSTREAM and
# GRUND_WEB_ROOT overrides.
set -euo pipefail

ip=${1:?usage: grund-vps-remote.sh IP [HOST]}
host=${2:-${ip//./-}.sslip.io}
here=$(cd "$(dirname "$0")" && pwd)
dest=${GRUND_CADDY_DIR:-/opt/grund}
container=${GRUND_CADDY_CONTAINER:-caddy}

export GRUND_IP=$ip GRUND_HOST=$host

render() {
	python3 - "$here/Caddyfile" "$dest/caddy.env" <<'EOF'
import os, re, sys
text = open(sys.argv[1]).read()
# KEY=VALUE lines, read literally: a bcrypt hash is full of "$".
values = {}
for line in open(sys.argv[2]):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        name, raw = line.split("=", 1)
        values[name.strip()] = raw.strip().strip("'\"")
values.update({name: os.environ[name] for name in ("GRUND_IP", "GRUND_HOST")})
def value(match):
    name, default = match.group(1), match.group(3)
    if name in values:
        return values[name]
    if default is None:
        sys.exit(f"{name} is not set")
    return default
sys.stdout.write(re.sub(r"\{\$([A-Z0-9_]+)(:([^}]*))?\}", value, text))
EOF
}

render > "$dest/Caddyfile.new"
if grep -Eq '^http://[^{]*\{' "$dest/Caddyfile.new" && awk '/^http:\/\//{site=1} site&&/reverse_proxy/{bad=1} /^\}/{site=0} END{exit !bad}' "$dest/Caddyfile.new"; then
	echo "refusing: a plain-http site proxies requests" >&2
	exit 1
fi
docker cp "$dest/Caddyfile.new" "$container:/tmp/Caddyfile.new"
docker exec "$container" caddy adapt --config /tmp/Caddyfile.new --adapter caddyfile > /dev/null
[ -f "$dest/Caddyfile" ] && cp "$dest/Caddyfile" "$dest/Caddyfile.bak-$(date -u +%Y%m%dT%H%M%SZ)"
mv "$dest/Caddyfile.new" "$dest/Caddyfile"
docker exec "$container" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
echo "https://$host is live; http://$ip redirects there"
