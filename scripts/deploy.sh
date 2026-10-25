#!/usr/bin/env bash
# Deploy a pushed branch to a contest server: pull, place changed configs, build, restart.
# Copy this into each contest repo and edit the variables below.
#
# Usage: ./deploy.sh <ssh-host> [branch]
set -euo pipefail

HOST=${1:?usage: $0 <ssh-host> [branch]}
BRANCH=${2:-main}

# --- per-contest settings ---
APP_DIR=/home/isucon/private_isu       # repo root on the server
BUILD_DIR=$APP_DIR/webapp/golang
BUILD_CMD="go build -o app"
APP_SERVICE=isu-go
ENV_FILE=/home/isucon/env.sh           # sourced before build to get the toolchain on PATH
# ----------------------------

# ssh joins its arguments into one string for the remote shell, so quote each one with %q
# shellcheck disable=SC2029  # client-side expansion is intended
ssh "$HOST" "bash -s -- $(printf '%q ' "$BRANCH" "$APP_DIR" "$BUILD_DIR" "$BUILD_CMD" "$APP_SERVICE" "$ENV_FILE")" <<'REMOTE'
set -euo pipefail
BRANCH=$1 APP_DIR=$2 BUILD_DIR=$3 BUILD_CMD=$4 APP_SERVICE=$5 ENV_FILE=$6
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
if has_changed /etc/mysql/; then
  echo "==> restarting mysql"
  sudo systemctl restart mysql
fi
if has_changed /etc/nginx/; then
  echo "==> reloading nginx"
  sudo nginx -t
  sudo systemctl reload nginx
fi

echo "==> building"
as_isucon bash -c "source '$ENV_FILE' && cd '$BUILD_DIR' && $BUILD_CMD"

echo "==> restarting $APP_SERVICE"
sudo systemctl restart "$APP_SERVICE"
sleep 1
echo "==> GET / -> $(curl -s -o /dev/null -w '%{http_code}' http://localhost/)"
REMOTE
