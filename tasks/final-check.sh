#!/usr/bin/env bash
# 副作用: 読取りだけ（手元のruns/へ結果を記録）
set -euo pipefail
if [[ ${1:-} == --help ]]; then
  echo 'Usage: tk final-check [--detail] [host...|@app]'
  echo 'Reads only: checkout, operation records, systemd services, logs and optional profiler port.'
  echo 'Checks host nginx/mysql units only; container services are not inspected.'
  exit 0
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$root/lib/client.py" final-check "$@"
