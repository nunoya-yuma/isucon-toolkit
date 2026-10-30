#!/usr/bin/env bash
set -euo pipefail
tk_load_config() {
  local project config
  project=$(git rev-parse --show-toplevel 2>/dev/null) || project=$PWD
  config=${TK_CONFIG:-$project/tk.env}
  [[ -f $config ]] || { echo "NG: config not found: $config" >&2; exit 2; }
  # tk.env is trusted local shell configuration, never sent wholesale to a server.
  # shellcheck disable=SC1090
  source "$config"
  export TK_HOSTS TK_ROLE_app APP_DIR APP_USER APP_SERVICE READY_URL
  export BUILD_CMD=${BUILD_CMD:-} READY_HOST=${READY_HOST:-}
  export READY_CODES=${READY_CODES:-200} READY_TIMEOUT=${READY_TIMEOUT:-60}
  export TK_ACTOR=${TK_ACTOR:-} TK_PROJECT_ROOT=$project
  export FINAL_PROFILER_PORT=${FINAL_PROFILER_PORT:-} REBOOT_TIMEOUT=${REBOOT_TIMEOUT:-300}
}
