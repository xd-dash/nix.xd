#!/usr/bin/env bash
set -Eeuo pipefail

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Linux ]] || fail 'Native Linux required for store-recreation module'
[[ "${NIX_XD_PROVIDER:-podman}" == podman ]] || fail 'Podman required'
scope="${NIX_XD_SCOPE:-nix-xd-amd64}"
system="${NIX_XD_SYSTEM:-x86_64-linux}"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || fail 'Invalid scope'
case "$system:$(uname -m)" in
  x86_64-linux:x86_64|aarch64-linux:aarch64) ;;
  *) fail 'Host/architecture mismatch' ;;
esac
image="localhost/nix-xd:$([[ "$system" == x86_64-linux ]] && echo amd64 || echo arm64)"
volume="$scope-store"
for cmd in podman systemctl sha256sum; do command -v "$cmd" >/dev/null || fail "Missing $cmd"; done
[[ "$(podman info --format '{{.Host.Security.Rootless}}')" == true ]] || fail 'Rootless Podman required'

diagnose() {
  systemctl --user --no-pager status "$scope.service" >&2 || true
  journalctl --user --no-pager -u "$scope.service" -n 80 >&2 || true
}
trap 'rc=$?; if (( rc != 0 )); then diagnose; fi' EXIT

assert_owner() {
  [[ "$(podman inspect "$scope" --format '{{.State.Running}}')" == true ]] ||
    fail 'Owner container not running'
  [[ "$(podman inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')" == "$volume" ]] ||
    fail 'Unexpected authoritative /nix volume'
  podman exec "$scope" /bin/sh -ec '
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
  podman exec "$scope" /bin/sh -ec '
    resolved="$(realpath -e /nix/home/nixuser/.nix-profile/bin/nix)"
    printf "%s\n" "$resolved"
    sha256sum "$resolved"
    nix --version
  '
}

printf 'STORE_RECREATION_STEP=preflight system=%s scope=%s volume=%s\n' "$system" "$scope" "$volume"
podman volume exists "$volume" || fail 'Missing Nix store volume'
podman image exists "$image" || fail 'Missing expected image'
assert_owner
before_id="$(podman inspect "$scope" --format '{{.Id}}')"
before_mount="$(podman volume inspect "$volume" --format '{{.Mountpoint}}')"
before_image="$(podman inspect "$scope" --format '{{.Image}}')"
before="$(snapshot)"
printf 'STORE_RECREATION_BEFORE_CONTAINER=%s\nSTORE_RECREATION_BEFORE_VOLUME=%s\n' "$before_id" "$before_mount"
printf 'STORE_RECREATION_BEFORE_PROFILE=%s\n' "$before"

printf 'STORE_RECREATION_STEP=restart-quadlet\n'
systemctl --user restart "$scope.service"
ready=0
for attempt in $(seq 1 30); do
  if podman container exists "$scope" && \
     [[ "$(podman inspect "$scope" --format '{{.State.Running}}' 2>/dev/null)" == true ]]; then
    after_id="$(podman inspect "$scope" --format '{{.Id}}')"
    if [[ "$after_id" != "$before_id" ]]; then ready=1; break; fi
  fi
  sleep 2
done
[[ "$ready" == 1 ]] || fail 'Quadlet failed to recreate container'
assert_owner
[[ "$(podman volume inspect "$volume" --format '{{.Mountpoint}}')" == "$before_mount" ]] ||
  fail 'Store mountpoint changed'
[[ "$(podman inspect "$scope" --format '{{.Image}}')" == "$before_image" ]] ||
  fail 'OCI image changed during recreation'
after="$(snapshot)"
[[ "$before" == "$after" ]] || fail 'Nix executable path, checksum or version changed'
printf 'STORE_RECREATION_CONTAINER_CHANGED=passed\n'
printf 'STORE_RECREATION_STORE_PRESERVED=passed\n'

printf 'STORE_RECREATION_STEP=readonly-export\n'
NIX_XD_SCOPE="$scope" NIX_XD_IMAGE="$image" COREOS_NIX_STORE_VOLUME="$volume" \
  bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/nix-xd-store-export-check"
printf 'STORE_RECREATION_RESULT=passed system=%s scope=%s volume=%s\n' "$system" "$scope" "$volume"
