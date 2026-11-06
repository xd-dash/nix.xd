#!/usr/bin/env bash
set -euo pipefail

# Apple Container: Linux OCI workloads in lightweight per-container VMs.
# No Podman Machine, Quadlet, or macOS host Nix installation.
die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || die "Requires Apple Silicon macOS"
major="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$major" =~ ^[0-9]+$ && "$major" -ge 26 ]] || die "Apple container requires macOS 26+"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
image="${NIX_XD_IMAGE:-localhost/nix-xd:arm64}"
volume="$scope-store"
workspaces="${NIX_XD_WORKSPACES:?NIX_XD_WORKSPACES required}"
workspace_mode="${NIX_XD_WORKSPACE_MODE:-bind}"
[[ "$workspace_mode" == bind || "$workspace_mode" == staged ]] || die "Workspace mode must be bind or staged"
[[ -d "$workspaces" ]] || die "Host workspace directory does not exist: $workspaces"
workspaces="$(cd "$workspaces" && pwd -P)"
[[ "$workspaces" != / && "$workspaces" != *:* ]] || die "Unsafe workspace mount source"
smoke_source="${NIX_XD_SMOKE_SOURCE:-}"
exchange_root="${NIX_XD_EXCHANGE_ROOT:-}"
smoke_access="${NIX_XD_SMOKE_ACCESS:-readwrite}"
exchange_access="${NIX_XD_EXCHANGE_ACCESS:-readwrite}"
[[ "$smoke_access" == readwrite || "$smoke_access" == readonly ]] || die "Invalid Smoke access"
[[ "$exchange_access" == readwrite || "$exchange_access" == readonly ]] || die "Invalid exchange access"
if [[ -n "$smoke_source" || -n "$exchange_root" ]]; then
  [[ "$workspace_mode" == bind && -n "$smoke_source" && -n "$exchange_root" ]] ||
    die "Smoke and exchange must both be mounted with WORKSPACE_MODE=bind"
  [[ -d "$smoke_source" && -f "$smoke_source/go.mod" ]] || die "Smoke Go checkout missing"
  [[ -d "$exchange_root" && -f "$exchange_root/.nix-xd-exchange" ]] ||
    die "Exchange directory must exist with .nix-xd-exchange marker"
  smoke_source="$(cd "$smoke_source" && pwd -P)"
  exchange_root="$(cd "$exchange_root" && pwd -P)"
  for path in "$smoke_source" "$exchange_root"; do
    [[ "$path" != / && "$path" != *:* && "$path" != *","* ]] || die "Unsafe shared source path"
  done
  [[ "$smoke_source" != "$exchange_root" ]] || die "Smoke and exchange must differ"
fi
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || die "Invalid scope"

if ! command -v container >/dev/null 2>&1; then
  command -v brew >/dev/null 2>&1 || die "Install Homebrew first"
  say "Installing Apple's container CLI"
  brew install container
fi

say "Starting Apple's container services"
container system start --disable-kernel-install
# Installing the recommended Linux kernel is idempotent on current releases.
# Allow the CLI to determine whether the existing kernel is already adequate.
if ! container run --rm docker.io/library/alpine:3.23 uname -m >/dev/null 2>&1; then
  say "Installing the recommended container kernel"
  container system kernel set --recommended
fi
container run --rm docker.io/library/alpine:3.23 uname -m | grep -qx aarch64 ||
  die "Container runtime did not execute aarch64 Linux"

say "Building ARM Nix-Alpine"
container build --platform linux/arm64 -t "$image" "$repo/arm"
container run --rm "$image" nix --version

if container inspect "$scope" >/dev/null 2>&1; then
  say "Existing container found; preserving its filesystem"
  details="$(container inspect "$scope")"
  grep -Eq '"name"[[:space:]]*:[[:space:]]*"'"$volume"'"' <<< "$details" ||
    die "Existing container does not own $volume; refusing implicit replacement"
  if ! container exec "$scope" /bin/true >/dev/null 2>&1; then
    container start "$scope"
  fi
  if [[ -n "$smoke_source" ]]; then
    container exec "$scope" /bin/bash -ec '
      grep -Eq "[[:space:]]/smoke[[:space:]]" /proc/mounts
      grep -Eq "[[:space:]]/exchange[[:space:]]" /proc/mounts
      test -r /smoke/go.mod
      test -r /exchange/.nix-xd-exchange
    ' || die "Existing runner lacks Smoke/exchange mounts; use a new scope"
    local_hash="$(shasum -a 256 "$smoke_source/go.mod")"
    guest_hash="$(container exec "$scope" sha256sum /smoke/go.mod)"
    [[ "${local_hash%% *}" == "${guest_hash%% *}" ]] || die "Smoke mount mismatch"
    local_hash="$(shasum -a 256 "$exchange_root/.nix-xd-exchange")"
    guest_hash="$(container exec "$scope" sha256sum /exchange/.nix-xd-exchange)"
    [[ "${local_hash%% *}" == "${guest_hash%% *}" ]] || die "Exchange mount mismatch"
  fi

else
  if ! container volume inspect "$volume" >/dev/null 2>&1; then
    say "Creating persistent Nix store volume: $volume"
    container volume create --opt size="${NIX_XD_STORE_SIZE:-40G}" "$volume"
  fi
  
  # On Apple's runtime an empty volume overlays the image's /nix directory.
  # Seed it explicitly from the image; unlike Podman's behavior, do not assume
  # volume mounts automatically copy the image's preinstalled Nix store.
  say "Initializing Nix store volume if needed"
  container run --rm --user 0 --volume "$volume:/seed" "$image" \
    /bin/bash -ec '
      if [ ! -e /seed/.nix-xd-seeded ]; then
        if [ -n "$(find /seed -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)" ]; then
          echo "Refusing to overwrite existing unmarked volume" >&2
          exit 1
        fi
        cp -a /nix/. /seed/
        chown -R 1000:1000 /seed
        touch /seed/.nix-xd-seeded
      fi
    '
  say "Starting persistent ARM Nix-Alpine container"
  mount_args=()
  if [[ "$workspace_mode" == bind ]]; then
    mount_args+=(--mount "type=bind,source=$workspaces,target=/workspaces,readonly")
    if [[ -n "$smoke_source" ]]; then
      smoke_opts=""
      exchange_opts=""
      [[ "$smoke_access" == readonly ]] && smoke_opts=",readonly"
      [[ "$exchange_access" == readonly ]] && exchange_opts=",readonly"
      mount_args+=(--mount "type=bind,source=$smoke_source,target=/smoke$smoke_opts")
      mount_args+=(--mount "type=bind,source=$exchange_root,target=/exchange$exchange_opts")
    fi
  fi
  container run -d --name "$scope" \
    --volume "$volume:/nix" \
    "${mount_args[@]}" \
    "$image" sleep infinity
fi

container exec "$scope" nix --version
if [[ "$workspace_mode" == bind ]]; then
  container exec "$scope" /bin/bash -ec '
    grep -Eq "[[:space:]]/workspaces[[:space:]]" /proc/mounts
    test -r /workspaces/flake.nix
    test ! -w /workspaces
  ' || die "Read-only workspace mount could not be verified"
fi
if [[ -n "$smoke_source" ]]; then
  container exec "$scope" /bin/bash -ec '
    grep -Eq "[[:space:]]/smoke[[:space:]]" /proc/mounts
    grep -Eq "[[:space:]]/exchange[[:space:]]" /proc/mounts
    test -r /smoke/go.mod
    test -r /exchange/.nix-xd-exchange
  ' || die "Smoke/exchange mounts not established"
  if [[ "$smoke_access" == readonly ]]; then
    container exec "$scope" test ! -w /smoke || die "Smoke mount unexpectedly writable"
  else
    container exec "$scope" test -w /smoke || die "Smoke mount unexpectedly read-only"
  fi
  if [[ "$exchange_access" == readonly ]]; then
    container exec "$scope" test ! -w /exchange || die "Exchange unexpectedly writable"
  else
    container exec "$scope" test -w /exchange || die "Exchange not writable"
  fi
fi
say "Apple container provider ready: $scope (workspace mode: $workspace_mode)"
say "Use: make status PROVIDER=container; make shell PROVIDER=container"
