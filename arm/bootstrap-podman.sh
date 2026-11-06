#!/usr/bin/env bash
set -euo pipefail

# macOS is a Podman Machine client; the canonical Linux bootstrap owns Quadlets.
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
say() { printf '==> %s\n' "$*"; }

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] ||
  die "Podman Machine bootstrap requires Apple Silicon macOS"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
machine="${NIX_XD_MACHINE:-podman-machine-default}"
scope="${NIX_XD_SCOPE:-nix-xd-smoke-podman}"
workspaces="${NIX_XD_WORKSPACES:-$repo}"
pin="${NIX_ALPINE_REV:?Pinned NIX_ALPINE_REV required}"
checkout="${NIX_ALPINE_CHECKOUT:-nix-alpine/nix-alpine}"
[[ "$machine" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "Invalid machine"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || die "Invalid scope"
[[ "$pin" =~ ^[0-9a-f]{40}$ ]] || die "NIX_ALPINE_REV must be a full commit"
[[ "$checkout" == nix-alpine/nix-alpine ]] || die "Unsupported Nix-Alpine checkout location"
[[ -d "$workspaces" ]] || die "Missing workspace root"
workspaces="$(cd "$workspaces" && pwd -P)"
[[ "$workspaces" != / && "$workspaces" != *" "* ]] || die "Unsafe workspace path"
[[ "$workspaces" == "$repo" ]] || die "Podman bootstrap requires WORKSPACES=nix.xd root"

command -v podman >/dev/null 2>&1 || die "Podman is required (already installed)"
command -v git >/dev/null 2>&1 || die "Git is required"
if ! podman machine inspect "$machine" >/dev/null 2>&1; then
  say "Initializing rootless Podman Machine $machine"
  podman machine init --provider applehv --rootful=false "$machine"
fi
state="$(podman machine inspect "$machine" --format '{{.State}}')"
if [[ "$state" != running ]]; then
  say "Starting Podman Machine $machine"
  podman machine start --update-connection=false "$machine"
fi

# All container operations run inside the selected VM. The macOS default
# Podman connection may otherwise target a different machine or rootful store.
say "Validating rootless Podman Machine and shared host workspace"
podman machine ssh "$machine" bash -se -- "$workspaces" <<'REMOTE'
set -euo pipefail
root="$1"
[[ "$(uname -m)" == aarch64 ]] || { echo "Wrong VM architecture" >&2; exit 1; }
[[ "$(podman info --format '{{.Host.Security.Rootless}}')" == true ]] ||
  { echo "Podman in VM must be rootless" >&2; exit 1; }
[[ -f "$root/flake.nix" && -w "$root" ]] ||
  { echo "Mac workspace is not writable inside VM: $root" >&2; exit 1; }
for cmd in podman git systemctl realpath id bash; do
  command -v "$cmd" >/dev/null || { echo "VM missing $cmd" >&2; exit 1; }
done
systemctl --user show-environment >/dev/null ||
  { echo "VM user systemd is unavailable" >&2; exit 1; }
REMOTE

say "Synchronizing pinned upstream Nix-Alpine source (no forced reset)"
bash "$repo/bin/nix-xd-sync" \
  dash-xd/nix-alpine codex/nixxd-refresh-reset \
  "$workspaces" "$checkout" "$pin"

say "Delegating to canonical Nix-Alpine Linux Quadlet bootstrap"
podman machine ssh "$machine" bash -se -- "$workspaces" "$scope" "$checkout" <<'REMOTE'
set -euo pipefail
root="$1"
scope="$2"
checkout="$3"
source="$root/$checkout"
[[ -f "$source/local/bootstrap.sh" ]] || { echo "Nix-Alpine bootstrap missing" >&2; exit 1; }
[[ -f "$source/local/seed-store-volume.sh" ]] ||
  { echo "Pinned Nix-Alpine lacks safe volume seeding; update the pin" >&2; exit 1; }
export NIX_XD_ROOT="$root" WORKSPACES="$root"
export NIX_ALPINE_ROOT="$source"
export SCOPE="$scope" CONTAINER="$scope" SERVICE="$scope.service"
export VOLUME="$scope-store"
bash "$source/local/bootstrap.sh"
podman exec "$scope" bash -ec '
  test "$(id -u)" = 1000
  test "$(id -g)" = 1000
  test -w /nix
  test -w /workspaces
  test -r /workspaces/flake.nix
'
systemctl --user is-active --quiet "$scope.service"
REMOTE
say "Rootless Podman Nix-Alpine ready: $scope on $machine"
