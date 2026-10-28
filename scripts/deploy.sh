#!/usr/bin/env bash
# Deploy a pushed branch to a contest server: pull, place changed configs, build, restart.
# Settings are read from toolkit.env next to this script.
#
# Usage: ./deploy.sh <ssh-host> [branch]
set -euo pipefail

HOST=${1:?usage: $0 <ssh-host> [branch]}
BRANCH=${2:-main}
# shellcheck source=toolkit.env
source "$(dirname "$0")/toolkit.env"

# ssh joins its arguments into one string for the remote shell, so quote each one with %q
# shellcheck disable=SC2029  # client-side expansion is intended
ssh "$HOST" "bash -s -- $(printf '%q ' "$BRANCH" "$APP_DIR" "$BUILD_DIR" "$BUILD_CMD" "$APP_SERVICE" "$ENV_FILE" "$DB_NAME" "$HEALTH_URL")" <<'REMOTE'
set -euo pipefail
BRANCH=$1 APP_DIR=$2 BUILD_DIR=$3 BUILD_CMD=$4 APP_SERVICE=$5 ENV_FILE=$6 DB_NAME=$7 HEALTH_URL=$8
as_isucon() { sudo -u isucon "$@"; }

cd "$APP_DIR"

# Refuse to clobber edits made directly on the server
if [[ -n $(as_isucon git status --porcelain) ]]; then
  echo "ERROR: uncommitted changes on server; commit/push or discard them first" >&2
  as_isucon git status --short >&2
  exit 1
fi
as_isucon git fetch -q origin
as_isucon git checkout -q -B "$BRANCH" "origin/$BRANCH"
echo "==> $(as_isucon git log -1 --oneline)"

# server/ mirrors absolute paths; copy only files that differ so we restart only what changed
changed=()
while IFS= read -r -d '' src; do
  dst=/${src#server/}
  if ! sudo cmp -s "$src" "$dst"; then
    sudo mkdir -p "$(dirname "$dst")"
    sudo cp "$src" "$dst"   # overwriting keeps the existing owner and mode
    changed+=("$dst")
    echo "==> updated $dst"
  fi
done < <(find server -type f -print0)

has_changed() { [[ " ${changed[*]-} " == *" $1"* ]]; }

if has_changed /etc/systemd/; then
  sudo systemctl daemon-reload
fi
# A unit picks up a changed unit file or EnvironmentFile (e.g. env.sh) only on restart
units=()
for f in "${changed[@]-}"; do
  [[ -n $f ]] || continue
  if [[ $f == /etc/systemd/system/*.service ]]; then
    units+=("$(basename "$f")")
  fi
  while IFS= read -r unit; do
    units+=("$(basename "$unit")")
  done < <(grep -lxF -e "EnvironmentFile=$f" -e "EnvironmentFile=-$f" /etc/systemd/system/*.service || true)
done
while IFS= read -r unit; do
  # the app itself is restarted below anyway
  [[ -n $unit && $unit != "$APP_SERVICE.service" ]] || continue
  # leave intentionally stopped services (e.g. other language implementations) stopped
  systemctl is-active --quiet "$unit" || continue
  echo "==> restarting $unit"
  sudo systemctl restart "$unit"
done < <(printf '%s\n' "${units[@]-}" | sort -u)
if has_changed /etc/mysql/; then
  echo "==> restarting mysql"
  sudo systemctl restart mysql
fi
if has_changed /etc/nginx/; then
  echo "==> reloading nginx"
  sudo nginx -t
  sudo systemctl reload nginx
fi

# Apply schema changes on every deploy. Re-running ADD INDEX fails with
# "Duplicate key name" (1061), which means it is already applied; any other error aborts.
# Only for contests whose /initialize does not recreate tables; otherwise edit the schema file instead.
# Not named sql/: contests often ship their own sql/ (e.g. ISUCON14) whose schema file drops tables.
if [[ -d migrations ]]; then
  for f in migrations/*.sql; do
    out=$(sudo mysql --force "$DB_NAME" < "$f" 2>&1 >/dev/null || true)
    errors=$(grep -v 'ERROR 1061' <<<"$out" || true)
    if [[ -n $errors ]]; then
      echo "ERROR: $f failed:" >&2
      echo "$errors" >&2
      exit 1
    fi
    echo "==> applied $f"
  done
fi

echo "==> building"
# Login shell: some contests put the toolchain on PATH only in the profile (e.g. ISUCON14)
as_isucon bash -lc "source '$ENV_FILE' && cd '$BUILD_DIR' && $BUILD_CMD"

echo "==> restarting $APP_SERVICE"
sudo systemctl restart "$APP_SERVICE"
sleep 1
# -k: practice environments often serve the contest's certificate after it has expired
echo "==> GET $HEALTH_URL -> $(curl -sk -o /dev/null -w '%{http_code}' "$HEALTH_URL")"
REMOTE
