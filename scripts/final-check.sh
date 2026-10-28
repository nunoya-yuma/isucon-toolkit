#!/usr/bin/env bash
# Check that servers are ready for the final benchmark and the post-contest check (which reboots them):
# latest commit deployed, enabled services running, logs and profiler turned off, app responding.
# Run it before and after rebooting every server. Settings are read from toolkit.env next to this script.
#
# Usage: ./final-check.sh <ssh-host>...
set -euo pipefail

[[ $# -gt 0 ]] || { echo "usage: $0 <ssh-host>..." >&2; exit 1; }
# shellcheck source=toolkit.env
source "$(dirname "$0")/toolkit.env"

failed=()
for host in "$@"; do
  echo "== $host"
  # shellcheck disable=SC2029  # client-side expansion is intended
  if ! ssh "$host" "bash -s -- $(printf '%q ' "$APP_DIR" "$APP_SERVICE" "$HEALTH_URL" "${PPROF_ADDR##*:}")" <<'REMOTE'; then
set -euo pipefail
APP_DIR=$1 APP_SERVICE=$2 HEALTH_URL=$3 PPROF_PORT=$4
status=0
ok() { echo "  OK  $*"; }
ng() { echo "  NG  $*"; status=1; }
as_isucon() { sudo -u isucon "$@"; }

cd "$APP_DIR"
if [[ -n $(as_isucon git status --porcelain) ]]; then
  ng "uncommitted changes on server"
else
  ok "no uncommitted changes"
fi
as_isucon git fetch -q origin
if [[ $(as_isucon git rev-parse HEAD) == "$(as_isucon git rev-parse '@{u}' 2>/dev/null)" ]]; then
  ok "deployed $(as_isucon git log -1 --format='%h %s')"
else
  ng "HEAD $(as_isucon git rev-parse --short HEAD) differs from its pushed branch; deploy again"
fi

# After the reboot, every enabled service must come back; a failed unit is easy to miss
failed_units=$(systemctl --failed --no-legend --plain | awk '{print $1}')
if [[ -n $failed_units ]]; then
  ng "failed units: $(echo "$failed_units" | tr '\n' ' ')"
else
  ok "no failed units"
fi
for unit in mysql nginx "$APP_SERVICE"; do
  if systemctl is-enabled --quiet "$unit"; then
    if systemctl is-active --quiet "$unit"; then ok "$unit enabled and active"; else ng "$unit enabled but not active"; fi
  else
    echo "  --  $unit disabled"
  fi
done

if systemctl is-active --quiet mysql; then
  logs=$(sudo mysql -NBe 'SELECT @@slow_query_log, @@general_log')
  if [[ $logs == $'0\t0' ]]; then ok "mysql slow/general log off"; else ng "mysql slow_query_log/general_log = $logs"; fi
fi

if systemctl is-active --quiet nginx; then
  # nginx -T prints the whole config, including files pulled in by include
  access_logs=$(sudo nginx -T 2>/dev/null | grep -E '^\s*access_log\s' | grep -vE '^\s*access_log\s+off;' || true)
  if [[ -z $access_logs ]]; then ok "nginx access_log off"; else ng "nginx access_log on: $(echo "$access_logs" | xargs)"; fi
fi

if [[ -n $(ss -ltnH "sport = :$PPROF_PORT") ]]; then
  ng "something listens on profiler port $PPROF_PORT"
else
  ok "profiler port $PPROF_PORT closed"
fi

if systemctl is-active --quiet "$APP_SERVICE"; then
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)
  # 4xx is fine (e.g. auth required); 5xx or no response means the app is not serving
  if [[ $code =~ ^[1-4] ]]; then ok "GET $HEALTH_URL -> $code"; else ng "GET $HEALTH_URL -> $code"; fi
fi
exit "$status"
REMOTE
    failed+=("$host")
  fi
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "NG on: ${failed[*]}" >&2
  exit 1
fi
echo "all OK"
