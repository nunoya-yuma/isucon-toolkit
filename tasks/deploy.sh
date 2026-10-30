#!/usr/bin/env bash
# 副作用: 実機を変える：checkout・設定の配布・build・サービスの再起動
set -euo pipefail
if [[ ${1:-} == --help ]]; then
  echo 'Usage: tk deploy [--plan] <commit|branch> [host|@app]'
  echo 'Single host only. --plan reads only; migrations are never run.'
  exit 0
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$root/lib/client.py" deploy "$@"
