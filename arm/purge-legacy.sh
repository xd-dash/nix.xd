#!/usr/bin/env bash
set -Eeuo pipefail

action="${1:-}"
[[ "$action" == plan || "$action" == apply ]] || { echo 'Expected plan|apply' >&2; exit 2; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || { echo 'Requires Apple Silicon macOS' >&2; exit 1; }
command -v podman >/dev/null && command -v container >/dev/null || {
  echo 'Podman and Apple container CLIs are required' >&2; exit 1;
}
legacy=podman-machine-default
target=coreos-arm64
confirm="${NIX_XD_LEGACY_PURGE_CONFIRM:-}"
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
machine_state() { podman machine inspect "$1" --format '{{.State}}'; }

[[ "$(machine_state "$legacy")" == stopped ]] || fail 'Legacy Podman Machine must already be stopped'
[[ "$(machine_state "$target")" == stopped ]] || fail 'Qualified coreos-arm64 Machine must remain stopped during cleanup'
printf 'LEGACY_PURGE_STEP=preflight\n'
printf 'LEGACY_PURGE_TARGET_MACHINE=%s\nLEGACY_PURGE_PRESERVED_MACHINE=%s\n' "$legacy" "$target"

for name in nix-xd-arm nix-xd-bind; do
  if container inspect "$name" >/dev/null 2>&1; then
    printf 'LEGACY_PURGE_APPLE_CONTAINER=%s\n' "$name"
    container inspect "$name" | grep -E '"(reference|source|destination|state)"[[:space:]]*:' || true
    details="$(container inspect "$name")"
    [[ "$details" == *'localhost/nix-xd:arm64'* ]] ||
      fail "Container $name no longer has expected Nix-Alpine image; refusing deletion"
    [[ "$details" == *'"state" : "stopped"'* || "$details" == *'"state": "stopped"'* ]] ||
      fail "Container $name is not stopped"
  fi
done

for vol in nix-xd-arm-store nix-xd-bind-store; do
  if container volume inspect "$vol" >/dev/null 2>&1; then
    printf 'LEGACY_PURGE_APPLE_VOLUME=%s\n' "$vol"
  fi
done
printf 'LEGACY_PURGE_NOTE=Old age key and Smoke stores in %s are disposable; prior GHXD encrypted data may become undecryptable\n' "$legacy"
if [[ "$action" == plan ]]; then
  printf 'LEGACY_PURGE_RESULT=planned-no-changes\n'
  exit 0
fi

[[ "$confirm" == 'ERASE:podman-machine-default:apple-nix-xd-legacy' ]] ||
  fail 'Set LEGACY_PURGE_CONFIRM=ERASE:podman-machine-default:apple-nix-xd-legacy'

printf 'LEGACY_PURGE_STEP=delete-apple-containers\n'
for name in nix-xd-arm nix-xd-bind; do
  if container inspect "$name" >/dev/null 2>&1; then container delete "$name"; fi
done
printf 'LEGACY_PURGE_STEP=delete-apple-volumes\n'
for vol in nix-xd-arm-store nix-xd-bind-store; do
  if container volume inspect "$vol" >/dev/null 2>&1; then container volume delete "$vol"; fi
done
printf 'LEGACY_PURGE_STEP=delete-legacy-machine\n'
podman machine rm --force "$legacy"
if podman machine inspect "$legacy" >/dev/null 2>&1; then fail 'Legacy Podman Machine still present'; fi
[[ "$(machine_state "$target")" == stopped ]] || fail 'Qualified target Machine state changed'
for name in nix-xd-arm nix-xd-bind; do
  if container inspect "$name" >/dev/null 2>&1; then fail "Apple container still present: $name"; fi
done
for vol in nix-xd-arm-store nix-xd-bind-store; do
  if container volume inspect "$vol" >/dev/null 2>&1; then fail "Apple volume still present: $vol"; fi
done
printf 'LEGACY_PURGE_RESULT=passed preserved_machine=%s\n' "$target"
