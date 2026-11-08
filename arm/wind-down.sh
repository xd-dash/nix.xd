#!/usr/bin/env bash
set -Eeuo pipefail

action="${1:-}"
[[ "$action" == plan || "$action" == stop ]] || { echo 'Usage: wind-down.sh plan|stop' >&2; exit 2; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo 'Requires Apple Silicon macOS' >&2; exit 1; }
command -v podman >/dev/null || { echo 'Podman CLI missing' >&2; exit 1; }

say() { printf 'WIND_DOWN_STEP=%s\n' "$1"; }
state() { podman machine inspect "$1" --format '{{.State}}' 2>/dev/null || true; }
machine_exists() { podman machine inspect "$1" >/dev/null 2>&1; }

inventory() {
  say inventory
  printf 'WIND_DOWN_GIT_REV=%s\n' "$(git -C "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" rev-parse HEAD)"
  printf '%s\n' '--- Podman machines ---'
  podman machine list
  for machine in coreos-arm64 podman-machine-default; do
    if machine_exists "$machine"; then
      printf 'WIND_DOWN_MACHINE=%s state=%s\n' "$machine" "$(state "$machine")"
      if [[ "$(state "$machine")" == running ]]; then
        printf '%s\n' "--- $machine containers ---"
        podman --connection "$machine" ps -a --format '{{.Names}} | {{.Image}} | {{.Status}}'
        printf '%s\n' "--- $machine volumes ---"
        podman --connection "$machine" volume ls --format '{{.Name}}'
        printf '%s\n' "--- $machine user Quadlets ---"
        podman machine ssh "$machine" 'find "$HOME/.config/containers/systemd" -maxdepth 2 -type f -print 2>/dev/null || true'
      else
        printf 'WIND_DOWN_UNINSPECTED_MACHINE=%s\n' "$machine"
      fi
    fi
  done
  if command -v container >/dev/null; then
    printf '%s\n' '--- Apple containers ---'
    container list --all
    printf '%s\n' '--- Apple named volumes ---'
    container volume list
  fi
}

stop_known() {
  say stop
  if [[ "$(state coreos-arm64)" == running ]]; then
    printf '%s\n' 'Stopping nix-xd-arm user Quadlet'
    podman machine ssh coreos-arm64 systemctl --user stop nix-xd-arm.service
    printf '%s\n' 'Stopping Podman Machine coreos-arm64'
    podman machine stop coreos-arm64
  fi
  if command -v container >/dev/null; then
    for name in nix-xd-arm nix-xd-bind; do
      if container inspect "$name" >/dev/null 2>&1; then
        printf 'Stopping Apple Container %s\n' "$name"
        container stop "$name" || {
          printf 'error: could not stop Apple Container %s\n' "$name" >&2
          exit 1
        }
      fi
    done
  fi
  printf 'WIND_DOWN_STOP=passed\n'
}

inventory
if [[ "$action" == stop ]]; then
  stop_known
  inventory
  [[ "$(state coreos-arm64)" != running ]] || { echo 'coreos-arm64 still running' >&2; exit 1; }
  [[ "$(state podman-machine-default)" != running ]] || {
    echo 'Older Podman Machine is running; refusing to claim full wind-down' >&2
    exit 1
  }
  printf 'WIND_DOWN_RESULT=stopped-known-nix-xd-workloads;volumes-and-machines-retained\n'
else
  printf 'WIND_DOWN_RESULT=planned-no-changes\n'
fi
