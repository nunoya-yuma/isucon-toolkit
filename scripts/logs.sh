#!/usr/bin/env bash
# Clear access/slow logs before a benchmark, and analyze them after.
# Settings are read from toolkit.env next to this script.
#
# Usage:
#   ./logs.sh clear   <nginx-host> [db-host]   # run right before the benchmark
#   ./logs.sh analyze <nginx-host> [db-host]   # run after it; results are also saved under logs/<timestamp>/
# db-host defaults to nginx-host; give it when MySQL runs on another server.
set -euo pipefail

CMD=${1:?usage: $0 clear|analyze <nginx-host> [db-host]}
HOST=${2:?usage: $0 clear|analyze <nginx-host> [db-host]}
DB_HOST=${3:-$HOST}

# shellcheck source=toolkit.env
source "$(dirname "$0")/toolkit.env"

case $CMD in
  clear)
    # truncate (not mv) so nginx/mysql keep writing to the same file without a reopen
    ssh "$HOST" sudo truncate -s 0 "$NGINX_LOG"
    ssh "$DB_HOST" sudo truncate -s 0 "$SLOW_LOG"
    echo "cleared $NGINX_LOG on $HOST, $SLOW_LOG on $DB_HOST"
    ;;
  analyze)
    out=logs/$(date +%Y%m%d-%H%M%S)
    mkdir -p "$out"
    # shellcheck disable=SC2029  # client-side expansion is intended
    ssh "$HOST" "sudo alp ltsv --file $(printf %q "$NGINX_LOG") --sort sum -r -m $(printf %q "$ALP_MATCHING")" > "$out/alp.txt"
    # shellcheck disable=SC2029
    ssh "$DB_HOST" "sudo pt-query-digest $(printf %q "$SLOW_LOG")" > "$out/slow.txt"
    head -n 25 "$out/alp.txt"
    echo
    # Profile section: the ranking of queries by total time
    sed -n '/^# Profile/,/^$/p' "$out/slow.txt"
    echo "saved to $out/"
    ;;
  *)
    echo "unknown command: $CMD" >&2
    exit 1
    ;;
esac
