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

# Reuse the sole store owner before attempting any temporary volume mount.
# Apple Container does not permit concurrent named-volume attachments.
if container inspect "$scope" >/dev/null 2>&1; then
  say "Reusing existing ARM Nix-Alpine container: $scope"
  details="$(container inspect "$scope")"
  printf '%s\n' "$details" | grep -Eq '"name"[[:space:]]*:[[:space:]]*"'"$volume"'"' ||
    die "Existing container $scope does not attach expected store volume $volume"
  printf '%s\n' "$details" | grep -Fq '"reference" : "'"$image"'"' ||
    die "Existing container $scope uses an unexpected image; refusing implicit replacement"
  if ! container exec "$scope" /bin/true >/dev/null 2>&1; then
    container start "$scope"
  fi
  container exec "$scope" /bin/bash -ec '
    grep -Eq "[[:space:]]/nix[[:space:]]ext4[[:space:]]rw" /proc/mounts
    test -f /nix/.nix-xd-seeded
  ' || die "Existing container store is unmounted or unseeded; refusing destructive repair"
else
  if ! container volume inspect "$volume" >/dev/null 2>&1; then
    say "Creating persistent Nix store volume: $volume"
    container volume create --opt size="${NIX_XD_STORE_SIZE:-40G}" "$volume"
  fi

  # Seed only when no persistent runner owns the volume.
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
  container run -d --name "$scope" \
    --volume "$volume:/nix" \
    "$image" sleep infinity
fi

container exec "$scope" nix --version
say "Apple container provider ready: $scope"
say "Use: make status PROVIDER=container; make shell PROVIDER=container"
