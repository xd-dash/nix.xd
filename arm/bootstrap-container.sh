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
[[ -z "${NIX_XD_PEER_STORES:-}" && "${NIX_XD_STORE_VOLUME:-$volume}" == "$volume" ]] || die "Builder store overrides currently require PROVIDER=podman"
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

# Never copy the image store into the volume: the image contains no Nix store.
# An existing pre-direct-volume store must be redeployed explicitly, never migrated.
if container inspect "$scope" >/dev/null 2>&1; then
  say "Reusing existing ARM Nix-Alpine container: $scope"
  details="$(container inspect "$scope")"
  grep -Eq '"name"[[:space:]]*:[[:space:]]*"'"$volume"'"' <<< "$details" ||
    die "Existing container $scope does not attach expected store volume $volume"
  grep -Fq '"reference" : "'"$image"'"' <<< "$details" ||
    die "Existing container $scope uses an unexpected image; refusing implicit replacement"
  container exec "$scope" /bin/true >/dev/null 2>&1 || container start "$scope"
else
  if ! container volume inspect "$volume" >/dev/null 2>&1; then
    container volume create --opt size="${NIX_XD_STORE_SIZE:-40G}" "$volume"
  fi
  # Only prepare the mountpoint of a new/empty volume. No recursive changes.
  container run --rm --user 0 --volume "$volume:/nix" --entrypoint /bin/sh "$image" -ec '
    test -z "$(find /nix -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)" || {
      test -f /nix/.nix-xd-direct-volume-v2 || {
        echo "Nonempty unmarked Nix store: explicit redeployment required" >&2; exit 1;
      }
    }
    if test ! -f /nix/.nix-xd-direct-volume-v2; then
      chown 1000:1000 /nix
    fi
  '
  say "Starting direct-volume ARM Nix-Alpine bootstrap"
  container run -d --name "$scope" --volume "$volume:/nix" "$image" sleep infinity
fi
ready=0
for attempt in $(seq 1 120); do
  if container exec "$scope" /bin/sh -c 'test -f /nix/.nix-xd-direct-volume-v2 && nix --version >/dev/null' 2>/dev/null; then
    ready=1
    break
  fi
  sleep 5
done
[[ "$ready" == 1 ]] || die "Direct-volume Nix bootstrap not ready; inspect container logs"
container exec "$scope" /bin/sh -ec '
  grep -Eq " /nix rw(,| )" /proc/self/mountinfo
  test -f /nix/.nix-xd-direct-volume-v2
  nix store info >/dev/null
' || die "Direct-volume Nix store validation failed"
container exec "$scope" nix --version
say "Apple container provider ready: $scope"
say "Use: make status PROVIDER=container; make shell PROVIDER=container"
