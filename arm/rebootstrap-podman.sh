#!/usr/bin/env bash
set -Eeuo pipefail

action="${1:-}"
machine="${NIX_XD_MACHINE:-podman-machine-default}"
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
image="${NIX_XD_IMAGE:-localhost/nix-xd:arm64}"
volume="$scope-store"
confirm="${NIX_XD_CONFIRM_RESET:-}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { printf "error: %s\n" "$*" >&2; exit 1; }
step() { printf "ARM_REBOOTSTRAP_STEP=%s\n" "$1"; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail "Requires Apple Silicon Mac"
[[ "$machine" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || fail "Invalid machine"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || fail "Invalid scope"
[[ "$image" == localhost/nix-xd:arm64 ]] || fail "Unexpected image; use default ARM bootstrap image"
[[ "$action" == diagnose || "$action" == preflight || "$action" == reset || "$action" == bootstrap || "$action" == verify || "$action" == all ]] ||
  fail "Usage: rebootstrap-podman diagnose|preflight|reset|bootstrap|verify|all"
[[ "$(podman machine inspect "$machine" --format "{{.State}}")" == running ]] ||
  fail "Selected Podman Machine must already be running"
p=(podman --connection "$machine")

diagnose() {
  step diagnose
  podman machine ssh "$machine" systemctl --user --no-pager status "$scope.service" || true
  if "${p[@]}" container exists "$scope"; then
    "${p[@]}" inspect "$scope" --format 'container={{.Name}} state={{.State.Status}} exit={{.State.ExitCode}}'
    printf '%s\n' '--- initialization log ---'
    "${p[@]}" logs --tail 160 "$scope" 2>&1 || true
    printf '%s\n' '--- persistent store state ---'
    "${p[@]}" exec "$scope" /bin/sh -ec '
      if test -f /nix/.nix-xd-direct-volume-v1; then echo STORE_MARKER=present; else echo STORE_MARKER=absent; fi
      if test -d /nix/store; then echo STORE_DIR=present; else echo STORE_DIR=absent; fi
      if test -x /nix/var/nix/profiles/default/bin/nix; then echo STORE_NIX_PROFILE=present; else echo STORE_NIX_PROFILE=absent; fi
    ' || true
  else
    echo 'OWNER_CONTAINER=missing'
  fi
  printf '%s\n' '--- complete user-service journal (most recent 150 lines) ---'
  podman machine ssh "$machine" journalctl --user --no-pager -o cat -u "$scope.service" -n 150 2>&1 || true
  printf '%s\n' '--- read-only named-volume inspection ---'
  if "${p[@]}" volume exists "$volume"; then
    "${p[@]}" run --rm --pull=never --user 0:0 \
      --mount "type=volume,src=$volume,dst=/nix,ro" \
      --entrypoint /bin/sh "$image" -ec '
        stat -c "STORE_ROOT uid=%u gid=%g mode=%a" /nix
        if test -f /nix/.nix-xd-direct-volume-v1; then echo STORE_MARKER=present; else echo STORE_MARKER=absent; fi
        if test -d /nix/store; then echo STORE_DIR=present; else echo STORE_DIR=absent; fi
        if test -x /nix/var/nix/profiles/default/bin/nix; then echo STORE_NIX_PROFILE=present; else echo STORE_NIX_PROFILE=absent; fi
        find /nix -mindepth 1 -maxdepth 2 -print | head -n 40
      ' || true
  else
    echo 'STORE_VOLUME=missing'
  fi
  printf 'ARM_REBOOTSTRAP_DIAGNOSIS=complete\n'
}

preflight() {
  step preflight
  [[ "$(podman machine ssh "$machine" uname -m)" == aarch64 ]] || fail "Machine is not ARM64"
  [[ "$("${p[@]}" info --format "{{.Host.Security.Rootless}}")" == true ]] || fail "Machine Podman must be rootless"
  printf "ARM_REBOOTSTRAP_MACHINE=%s SCOPE=%s VOLUME=%s\n" "$machine" "$scope" "$volume"
  printf "ARM_REBOOTSTRAP_NOTE=Only the named Nix-Alpine owner and volume are reset; machine and qualified evidence are retained\n"
  "${p[@]}" ps -a --filter "name=coreos-starwisp" --format "{{.Names}} {{.Status}}"
  if "${p[@]}" volume exists "$volume"; then
    "${p[@]}" volume inspect "$volume" --format "volume={{.Name}} mountpoint={{.Mountpoint}}"
  fi
  if "${p[@]}" container exists "$scope"; then
    "${p[@]}" inspect "$scope" --format "container={{.Name}} state={{.State.Status}}"
    owner_volume="$("${p[@]}" inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')"
    [[ "$owner_volume" == "$volume" ]] || fail "Existing owner has unexpected /nix volume: $owner_volume"
  fi
  printf "ARM_REBOOTSTRAP_PREFLIGHT=passed\n"
}

reset() {
  step reset
  [[ "$confirm" == "ERASE:$machine:$scope:$volume" ]] ||
    fail "Reset requires NIX_XD_CONFIRM_RESET=ERASE:$machine:$scope:$volume"
  # No running QEMU guest may retain access to the store. The script never deletes guest state.
  for guest in coreos-starwisp coreos-starwisp-9p coreos-starwisp-9p-fixed; do
    if "${p[@]}" container exists "$guest"; then
      status="$("${p[@]}" inspect "$guest" --format "{{.State.Status}}")"
      [[ "$status" == exited || "$status" == created ]] ||
        fail "Guest $guest is $status; stop it and archive evidence before reset"
    fi
  done
  podman machine ssh "$machine" systemctl --user stop "$scope.service" ||
    fail "Cannot stop Nix-Alpine service; investigate before deleting volume"
  if "${p[@]}" container exists "$scope"; then
    status="$("${p[@]}" inspect "$scope" --format "{{.State.Status}}")"
    [[ "$status" != running ]] || fail "Owner container is still running"
    "${p[@]}" rm "$scope"
  fi
  # Remove only explicitly known stopped QEMU test containers. Preserve disks and evidence.
  for guest in coreos-starwisp coreos-starwisp-9p coreos-starwisp-9p-fixed; do
    if "${p[@]}" container exists "$guest"; then "${p[@]}" rm "$guest"; fi
  done
  if "${p[@]}" volume exists "$volume"; then
    "${p[@]}" volume rm "$volume" || fail "Volume still in use; refusing forced removal"
  fi
  printf "ARM_REBOOTSTRAP_RESET=passed volume=%s\n" "$volume"
}

bootstrap() {
  step bootstrap
  NIX_XD_MACHINE_BOOTSTRAP=0 NIX_XD_MACHINE="$machine" NIX_XD_SCOPE="$scope" NIX_XD_IMAGE="$image" \
    bash "$repo/arm/bootstrap-podman.sh"
  printf "ARM_REBOOTSTRAP_BOOTSTRAP=passed\n"
}

verify() {
  step verify
  NIX_XD_MACHINE="$machine" NIX_XD_SCOPE="$scope" NIX_XD_IMAGE="$image" \
    COREOS_NIX_STORE_VOLUME="$volume" bash "$repo/bin/nix-xd-store-export-check"
  printf "ARM_REBOOTSTRAP_RESULT=passed machine=%s volume=%s\n" "$machine" "$volume"
}

case "$action" in
  diagnose) diagnose ;;
  preflight) preflight ;;
  reset) preflight; reset ;;
  bootstrap) bootstrap ;;
  verify) verify ;;
  all) preflight; reset; bootstrap; verify ;;
esac
