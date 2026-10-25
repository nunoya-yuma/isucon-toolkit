#!/usr/bin/env bash
# Install log analysis tools on a contest server: alp (nginx) and pt-query-digest (MySQL).
#
# Usage: ./install-tools.sh <ssh-host>
set -euo pipefail

HOST=${1:?usage: $0 <ssh-host>}
ALP_VERSION=v1.0.22   # https://github.com/tkuchiki/alp/releases

# shellcheck disable=SC2029  # client-side expansion is intended
ssh "$HOST" "bash -s -- $(printf '%q ' "$ALP_VERSION")" <<'REMOTE'
set -euo pipefail
ALP_VERSION=$1

sudo apt-get update -qq
# NEEDRESTART_MODE=l: only list services needing restart; otherwise needrestart restarts mysql/nginx/app
sudo NEEDRESTART_MODE=l DEBIAN_FRONTEND=noninteractive apt-get install -y -qq percona-toolkit unzip >/dev/null

tmp=$(mktemp -d)
curl -fsSL -o "$tmp/alp.zip" "https://github.com/tkuchiki/alp/releases/download/$ALP_VERSION/alp_linux_amd64.zip"
unzip -q "$tmp/alp.zip" -d "$tmp"
sudo install "$tmp/alp" /usr/local/bin/alp
rm -rf "$tmp"

alp --version
pt-query-digest --version
REMOTE
