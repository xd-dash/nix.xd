#!/usr/bin/env bash
set -Eeuo pipefail

machine="${NIX_XD_LEGACY_MACHINE:-podman-machine-default}"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo 'error: Apple Silicon macOS required' >&2; exit 1; }
[[ "$machine" == podman-machine-default ]] || { echo 'error: only the known legacy machine may be inspected' >&2; exit 1; }
command -v podman >/dev/null || { echo 'error: podman is required' >&2; exit 1; }
command -v container >/dev/null || { echo 'error: Apple container CLI is required' >&2; exit 1; }

printf 'LEGACY_INSPECT_STEP=preflight\n'
before="$(podman machine inspect "$machine" --format '{{.State}}')" || { echo 'error: legacy Podman Machine not found' >&2; exit 1; }
[[ "$before" == stopped ]] || { echo 'error: legacy machine must be stopped before controlled inspection' >&2; exit 1; }
[[ "$(podman machine inspect coreos-arm64 --format '{{.State}}')" == stopped ]] || {
  echo 'error: qualified machine must remain stopped during legacy inspection' >&2
  exit 1
}

started=0
cleanup() {
  rc=$?
  trap - EXIT
  if (( started )); then
    printf 'LEGACY_INSPECT_STEP=stop-legacy-machine\n'
    podman machine stop "$machine" || rc=1
  fi
  printf 'LEGACY_INSPECT_EXIT=%s\n' "$rc"
  exit "$rc"
}
trap cleanup EXIT

printf 'LEGACY_INSPECT_STEP=apple-container-metadata\n'
for name in nix-xd-arm nix-xd-bind; do
  printf 'LEGACY_APPLE_CONTAINER=%s\n' "$name"
  if container inspect "$name" >/dev/null 2>&1; then
    container inspect "$name" | grep -E '"(name|state|reference|source|destination)"[[:space:]]*:' || true
  else
    printf 'LEGACY_APPLE_CONTAINER_MISSING=%s\n' "$name"
  fi
done
for volume in nix-xd-arm-store nix-xd-bind-store; do
  printf 'LEGACY_APPLE_VOLUME=%s\n' "$volume"
  container volume inspect "$volume" || true
done

printf 'LEGACY_INSPECT_STEP=start-legacy-machine\n'
podman machine start --update-connection=false "$machine"
started=1
printf 'LEGACY_INSPECT_STEP=podman-inventory\n'
p=(podman --connection "$machine")
printf '%s\n' '--- containers ---'
"${p[@]}" ps -a --format '{{.Names}} | {{.Image}} | {{.Status}}'
printf '%s\n' '--- images ---'
"${p[@]}" images --format '{{.Repository}}:{{.Tag}} | {{.ID}}'
printf '%s\n' '--- volumes ---'
"${p[@]}" volume ls --format '{{.Name}}'
printf '%s\n' '--- user Quadlets ---'
podman machine ssh "$machine" 'find "$HOME/.config/containers/systemd" -maxdepth 2 -type f -print 2>/dev/null || true'
printf 'LEGACY_INSPECT_RESULT=inventory-captured\n'
