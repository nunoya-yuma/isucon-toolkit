#!/usr/bin/env bash
# 副作用: 実機を変える：指定順に1台ずつ再起動（元のboot IDには戻せない）
set -euo pipefail
if [[ ${1:-} == --help ]]; then
  echo 'Usage: tk reboot [--plan] [host...|@app]'
  echo 'Reboots sequentially; stops if a request fails or boot ID change cannot be confirmed.'
  echo '--plan shows order only. Run final-check afterwards; unavailable hosts need manual recovery.'
  exit 0
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$root/lib/client.py" reboot "$@"
