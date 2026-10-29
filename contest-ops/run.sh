#!/usr/bin/env bash
set -euo pipefail

ops_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
usage() {
  cat <<'USAGE'
Usage: ./run.sh COMMAND -i INVENTORY -c CONFIG [options]
Commands:
  inspect   Save server facts, services, listeners, and resource information
  snapshot  Download archives of explicitly selected original source/config
  bootstrap Install selected diagnostic packages and optional journal limits
  nginx-plan    Save selected nginx changes and validate without applying
  nginx-apply   Back up, validate, apply, reload; recover on failure
  nginx-restore Restore a successful nginx apply by its run ID
  validate  Check syntax and config without connecting to servers
  deploy    Upload local sources, build, switch release, restart, check health
  verify    Check application, configured services, and TCP connections
  rollback  Switch applications back to their previous releases
  configure Apply explicitly configured templates and commands
  reboot    Reboot inventory hosts, then run verify (explicit operation)
Options:
  -i, --inventory PATH       SSH inventory
  -c, --config PATH          Contest configuration YAML
  -k, --private-key PATH     SSH private key (overrides inventory)
  -u, --user USER            SSH user (overrides inventory)
  --project-root PATH       Source project root (default: this repository)
  -e, --extra-vars VALUE     Additional Ansible vars or @file (repeatable)
  --ask-become-pass          Prompt for sudo password
  -h, --help                Show this help
USAGE
}
fail() { echo "Error: $*" >&2; exit 2; }
[[ $# -gt 0 ]] || { usage; exit 2; }
case "$1" in -h|--help) usage; exit 0;; esac
ops_action="$1"; shift
case "$ops_action" in nginx-plan|nginx-apply|nginx-restore|inspect|snapshot|bootstrap|validate|deploy|verify|rollback|configure|reboot) ;; *) fail "Unknown command: $ops_action";; esac
ops_inventory=''; ops_config=''; ops_key=''; ops_user=''
ops_project_root="$(cd -- "$ops_root/../.." && pwd)"
ops_extra=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--inventory|-c|--config|-k|--private-key|-u|--user|--project-root|-e|--extra-vars)
      [[ $# -ge 2 && -n "$2" ]] || fail "Missing value for $1"
      case "$1" in
        -i|--inventory) ops_inventory="$2";;
        -c|--config) ops_config="$2";;
        -k|--private-key) ops_key="$2";;
        -u|--user) ops_user="$2";;
        --project-root) ops_project_root="$2";;
        -e|--extra-vars) ops_extra+=(--extra-vars "$2");;
      esac
      shift 2;;
    --ask-become-pass) ops_extra+=(--ask-become-pass); shift;;
    -h|--help) usage; exit 0;;
    *) fail "Unknown option: $1";;
  esac
done
[[ -n "$ops_inventory" && -n "$ops_config" ]] || fail 'Specify -i INVENTORY and -c CONFIG'
[[ -f "$ops_inventory" && -f "$ops_config" ]] || fail 'Inventory or config file does not exist'
[[ -z "$ops_key" || -f "$ops_key" ]] || fail 'Private key file does not exist'
[[ -d "$ops_project_root" ]] || fail 'Project root does not exist'
for ops_program in ansible-playbook python3 flock; do
  command -v "$ops_program" >/dev/null || fail "Required command not found: $ops_program"
done
ops_inventory="$(realpath -- "$ops_inventory")"
ops_config="$(realpath -- "$ops_config")"
mkdir -p "$ops_root/.local/tmp"
export ANSIBLE_CONFIG="$ops_root/ansible.cfg"
export ANSIBLE_LOCAL_TEMP="${ANSIBLE_LOCAL_TEMP:-$ops_root/.local/tmp}"
ops_runtime="$(mktemp "$ops_root/.local/tmp/runtime.XXXXXX.json")"
trap 'rm -f -- "$ops_runtime"' EXIT
python3 - "$ops_runtime" "$ops_config" "$ops_project_root" "$ops_key" "$ops_user" "$ops_action" <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sys
target, config, project, key, user, action = sys.argv[1:]
values = {'ops_config_file': config, 'ops_project_root': str(Path(project).resolve()),
          'ops_run_id': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4)}
if action.startswith('nginx-'):
    values['ops_nginx_action'] = action.removeprefix('nginx-')
if key:
    values['ansible_ssh_private_key_file'] = str(Path(key).resolve())
if user:
    values['ansible_user'] = user
Path(target).write_text(json.dumps(values))
PY
# Serialize operations launched from this checkout, including validation.
exec 9>"$ops_root/.local/operation.lock"
flock -n 9 || fail 'Another operation is running from this checkout'
cd -- "$ops_root"
ops_args=(-i "$ops_inventory" --extra-vars "@$ops_runtime" "${ops_extra[@]}")
if [[ "$ops_action" == validate ]]; then
  ansible-playbook "${ops_args[@]}" playbooks/deploy.yml --syntax-check
fi
ops_playbook="$ops_action"
case "$ops_action" in nginx-*) ops_playbook=nginx;; esac
ansible-playbook "${ops_args[@]}" "playbooks/$ops_playbook.yml"
