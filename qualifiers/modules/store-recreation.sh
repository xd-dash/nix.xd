#!/usr/bin/env bash
set -Eeuo pipefail

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
host="$(uname -s)"
[[ "${NIX_XD_PROVIDER:-podman}" == podman ]] || fail 'Podman required'
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
system="${NIX_XD_SYSTEM:-aarch64-linux}"
machine="${NIX_XD_MACHINE:-podman-machine-default}"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || fail 'Invalid scope'
[[ "$system" == aarch64-linux || "$system" == x86_64-linux ]] || fail 'Unsupported Nix system'
if [[ "$system" == aarch64-linux ]]; then default_image=localhost/nix-xd:arm64; else default_image=localhost/nix-xd:amd64; fi
image="${NIX_XD_IMAGE:-$default_image}"
volume="$scope-store"
command -v podman >/dev/null || fail 'Podman missing'
case "$host" in
  Darwin)
    [[ "$machine" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail 'Invalid Podman Machine'
    [[ "$(podman machine inspect "$machine" --format '{{.State}}')" == running ]] ||
      fail 'Podman Machine is not running'
    p=(podman --connection "$machine")
    service() { podman machine ssh "$machine" systemctl --user "$@"; }
    diagnose() {
      podman machine ssh "$machine" systemctl --user --no-pager status "$scope.service" >&2 || true
      podman machine ssh "$machine" journalctl --user --no-pager -u "$scope.service" -n 80 >&2 || true
    }
    ;;
  Linux)
    p=(podman)
    service() { systemctl --user "$@"; }
    diagnose() {
      systemctl --user --no-pager status "$scope.service" >&2 || true
      journalctl --user --no-pager -u "$scope.service" -n 80 >&2 || true
    }
    ;;
  *) fail 'Unsupported host OS' ;;
esac
[[ "$("${p[@]}" info --format '{{.Host.Security.Rootless}}')" == true ]] ||
  fail 'Rootless Podman required'
actual="$("${p[@]}" exec "$scope" uname -m)" || fail 'Nix-Alpine owner not running'
case "$system:$actual" in
  x86_64-linux:x86_64|aarch64-linux:aarch64|aarch64-linux:arm64) ;;
  *) fail "Runtime architecture mismatch: requested=$system actual=$actual" ;;
esac
trap 'rc=$?; if (( rc != 0 )); then diagnose; fi' EXIT

assert_owner() {
  [[ "$("${p[@]}" inspect "$scope" --format '{{.State.Running}}')" == true ]] ||
    fail 'Owner container not running'
  [[ "$("${p[@]}" inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')" == "$volume" ]] ||
    fail 'Unexpected authoritative /nix volume'
  "${p[@]}" exec "$scope" /bin/sh -ec '
    test -f /nix/.nix-xd-direct-volume-v2
    test -x /nix/home/nixuser/.nix-profile/bin/nix
    test "$(id -u)" = 1000
    grep -Eq " /nix rw(,| )" /proc/self/mountinfo
    resolved="$(realpath -e /nix/home/nixuser/.nix-profile/bin/nix)"
    case "$resolved" in /nix/store/*) ;; *) exit 1 ;; esac
    nix store info >/dev/null
  ' || fail 'Direct-volume owner invariants failed'
}
snapshot() {
  "${p[@]}" exec "$scope" /bin/sh -ec '
    resolved="$(realpath -e /nix/home/nixuser/.nix-profile/bin/nix)"
    printf "%s\n" "$resolved"
    sha256sum "$resolved"
    nix --version
  '
}

printf 'STORE_RECREATION_STEP=preflight host=%s system=%s scope=%s volume=%s\n' "$host" "$system" "$scope" "$volume"
"${p[@]}" volume exists "$volume" || fail 'Missing Nix store volume'
"${p[@]}" image exists "$image" || fail 'Missing expected image'
assert_owner
before_id="$("${p[@]}" inspect "$scope" --format '{{.Id}}')"
before_mount="$("${p[@]}" volume inspect "$volume" --format '{{.Mountpoint}}')"
before_image="$("${p[@]}" inspect "$scope" --format '{{.Image}}')"
before="$(snapshot)"
printf 'STORE_RECREATION_BEFORE_CONTAINER=%s\nSTORE_RECREATION_BEFORE_VOLUME=%s\n' "$before_id" "$before_mount"
printf 'STORE_RECREATION_BEFORE_PROFILE=%s\n' "$before"

printf 'STORE_RECREATION_STEP=restart-quadlet\n'
service restart "$scope.service"
ready=0
for attempt in $(seq 1 30); do
  if "${p[@]}" container exists "$scope" && \
     [[ "$("${p[@]}" inspect "$scope" --format '{{.State.Running}}' 2>/dev/null)" == true ]]; then
    after_id="$("${p[@]}" inspect "$scope" --format '{{.Id}}')"
    if [[ "$after_id" != "$before_id" ]]; then ready=1; break; fi
  fi
  sleep 2
done
[[ "$ready" == 1 ]] || fail 'Quadlet failed to recreate container'
assert_owner
[[ "$("${p[@]}" volume inspect "$volume" --format '{{.Mountpoint}}')" == "$before_mount" ]] ||
  fail 'Store mountpoint changed'
[[ "$("${p[@]}" inspect "$scope" --format '{{.Image}}')" == "$before_image" ]] ||
  fail 'OCI image changed during recreation'
after="$(snapshot)"
[[ "$before" == "$after" ]] || fail 'Nix executable path, checksum or version changed'
printf 'STORE_RECREATION_CONTAINER_CHANGED=passed\n'
printf 'STORE_RECREATION_STORE_PRESERVED=passed\n'

printf 'STORE_RECREATION_STEP=readonly-export\n'
NIX_XD_MACHINE="$machine" NIX_XD_SCOPE="$scope" NIX_XD_IMAGE="$image" COREOS_NIX_STORE_VOLUME="$volume" \
  bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/nix-xd-store-export-check"
printf 'STORE_RECREATION_RESULT=passed host=%s system=%s scope=%s volume=%s\n' "$host" "$system" "$scope" "$volume"
