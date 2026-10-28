#!/usr/bin/env bash
# Take CPU (pprof) and wall-clock (fgprof) profiles of the Go app while a benchmark runs.
# The app must expose them on localhost (see docs/runbook.md); this fetches them over ssh.
# Settings are read from toolkit.env next to this script.
#
# Usage: ./profile.sh <ssh-host> [seconds]   # start right after the benchmark starts
# View:  go tool pprof -http=: logs/<timestamp>/fgprof.pprof
set -euo pipefail

HOST=${1:?usage: $0 <ssh-host> [seconds]}
DURATION=${2:-60}

# shellcheck source=toolkit.env
source "$(dirname "$0")/toolkit.env"

out=logs/$(date +%Y%m%d-%H%M%S)
mkdir -p "$out"

fetch() {
  # shellcheck disable=SC2029  # client-side expansion is intended
  ssh "$HOST" "curl -fsS $(printf %q "http://$PPROF_ADDR$1?seconds=$DURATION")" > "$out/$2"
}

# Fetch both at once so they cover the same window of the benchmark
echo "profiling for ${DURATION}s..."
fetch /debug/pprof/profile cpu.pprof & cpu=$!
fetch /debug/fgprof fgprof.pprof & fg=$!
wait "$cpu"
wait "$fg"

echo "saved to $out/"
echo "view: go tool pprof -http=: $out/fgprof.pprof   # or cpu.pprof"
