#!/usr/bin/env bash
# 副作用: 読取りだけ（手元の runs/ には結果を書く）
set -euo pipefail
if [[ ${1:-} == --help ]]; then
  echo 'Usage: tk status [--detail] [host...|@app] (remote read only; 10s per host)'
  exit 0
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$root/lib/client.py" status "$@"
