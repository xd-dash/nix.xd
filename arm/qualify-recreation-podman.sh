#!/usr/bin/env bash
set -Eeuo pipefail

machine="${NIX_XD_MACHINE:-podman-machine-default}"
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
image="${NIX_XD_IMAGE:-localhost/nix-xd:arm64}"
volume="$scope-store"
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail 'Requires Apple Silicon macOS'
[[ "$machine" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail 'Invalid machine'
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || fail 'Invalid scope'
[[ "$image" == localhost/nix-xd:arm64 ]] || fail 'Unexpected ARM image'
[[ "$(podman machine inspect "$machine" --format '{{.State}}')" == running ]] || fail 'Podman Machine not running'
p=(podman --connection "$machine")

diagnose() {
  printf '%s\n' '--- Quadlet status ---' >&2
  podman machine ssh "$machine" systemctl --user --no-pager status "$scope.service" >&2 || true
  printf '%s\n' '--- service journal ---' >&2
  podman machine ssh "$machine" journalctl --user --no-pager -u "$scope.service" -n 90 >&2 || true
}
trap 'rc=$?; if (( rc != 0 )); then diagnose; fi' EXIT

assert_owner() {
  [[ "$("${p[@]}" inspect "$scope" --format '{{.State.Running}}')" == true ]] || fail 'Nix-Alpine not running'
  mounted="$("${p[@]}" inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')"
  [[ "$mounted" == "$volume" ]] || fail "Unexpected /nix volume: $mounted"
  "${p[@]}" exec "$scope" /bin/sh -ec '
    test -f /nix/.nix-xd-direct-volume-v2
    test -x /nix/home/nixuser/.nix-profile/bin/nix
    test "$(id -u)" = 1000
    grep -Eq " /nix rw(,| )" /proc/self/mountinfo
    resolved="$(realpath -e /nix/home/nixuser/.nix-profile/bin/nix)"
    case "$resolved" in /nix/store/*) ;; *) exit 1 ;; esac
    nix --version >/dev/null
    nix store info >/dev/null
  ' || fail 'Authoritative store not usable'
}
snapshot() {
  "${p[@]}" exec "$scope" /bin/sh -ec '
    readlink -f /nix/home/nixuser/.nix-profile/bin/nix
    sha256sum "$(readlink -f /nix/home/nixuser/.nix-profile/bin/nix)"
    nix --version
  '
}

printf 'RECREATION_STEP=preflight machine=%s scope=%s volume=%s\n' "$machine" "$scope" "$volume"
"${p[@]}" volume exists "$volume" || fail 'Named store volume missing'
assert_owner
old_id="$("${p[@]}" inspect "$scope" --format '{{.Id}}')"
old_mount="$("${p[@]}" volume inspect "$volume" --format '{{.Mountpoint}}')"
old_image="$("${p[@]}" inspect "$scope" --format '{{.Image}}')"
before="$(snapshot)"
printf 'RECREATION_BEFORE_CONTAINER=%s\nRECREATION_BEFORE_VOLUME=%s\nRECREATION_IMAGE=%s\n' "$old_id" "$old_mount" "$old_image"
printf 'RECREATION_BEFORE_PROFILE=%s\n' "$before"

printf 'RECREATION_STEP=recreate via=systemd-user-quadlet\n'
podman machine ssh "$machine" systemctl --user restart "$scope.service"

ready=0
for attempt in $(seq 1 30); do
  if "${p[@]}" container exists "$scope" && \
     [[ "$("${p[@]}" inspect "$scope" --format '{{.State.Running}}' 2>/dev/null)" == true ]]; then
    new_id="$("${p[@]}" inspect "$scope" --format '{{.Id}}')"
    if [[ "$new_id" != "$old_id" ]]; then ready=1; break; fi
  fi
  sleep 2
done
[[ "$ready" == 1 ]] || fail 'Quadlet failed to create a different running container'
assert_owner
new_mount="$("${p[@]}" volume inspect "$volume" --format '{{.Mountpoint}}')"
new_image="$("${p[@]}" inspect "$scope" --format '{{.Image}}')"
after="$(snapshot)"
[[ "$new_mount" == "$old_mount" ]] || fail 'Authoritative volume mountpoint changed'
[[ "$new_image" == "$old_image" ]] || fail 'Container image changed during recreation'
[[ "$after" == "$before" ]] || fail 'Persistent Nix executable identity or version changed'
printf 'RECREATION_AFTER_CONTAINER=%s\nRECREATION_AFTER_VOLUME=%s\n' "$new_id" "$new_mount"
printf 'RECREATION_AFTER_PROFILE=%s\n' "$after"
printf 'RECREATION_CONTAINER_CHANGED=passed\nRECREATION_STORE_PRESERVED=passed\n'

printf 'RECREATION_STEP=read-only-export\n'
NIX_XD_MACHINE="$machine" NIX_XD_SCOPE="$scope" NIX_XD_IMAGE="$image" \
  COREOS_NIX_STORE_VOLUME="$volume" bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bin/nix-xd-store-export-check"
printf 'ARM_RECREATION_RESULT=passed machine=%s scope=%s volume=%s\n' "$machine" "$scope" "$volume"
