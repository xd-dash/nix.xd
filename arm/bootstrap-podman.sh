#!/usr/bin/env bash
set -euo pipefail

# Apple Silicon host bootstrap. Run from a checkout of xd-dash/nix.xd.
# The host only needs Homebrew/Podman; Nix and Quadlet live in the Linux VM.

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
say() { printf '==> %s\n' "$*"; }

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] ||
  die "Requires Apple Silicon macOS"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$repo/arm/Dockerfile" ]] || die "Missing arm/Dockerfile"

machine="${NIX_XD_MACHINE:-podman-machine-default}"
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || die "Invalid scope"
[[ "$machine" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || die "Invalid machine name"
source "$repo/lib/builder-stores.sh"
builder_stores_init "$scope"
image="${NIX_XD_IMAGE:-localhost/nix-xd:arm64}"
unit="$scope.service"

if ! command -v podman >/dev/null 2>&1; then
  command -v brew >/dev/null 2>&1 || die "Install Homebrew first"
  say "Installing Podman"
  brew install podman
fi

if [[ "${NIX_XD_MACHINE_BOOTSTRAP:-1}" == 1 ]]; then
  NIX_XD_MACHINE_VERIFY="${NIX_XD_MACHINE_VERIFY:-0}" bash "$repo/bin/nix-xd-machine" init
else
  podman machine inspect "$machine" >/dev/null 2>&1 ||
    die "Missing machine $machine; run make machine-init or set MACHINE_BOOTSTRAP=1"
fi

if [[ "$(podman machine inspect "$machine" --format '{{.State}}')" != running ]]; then
  say "Starting Podman Machine: $machine"
  podman machine start "$machine"
fi

# The machine's rootless SSH connection is used explicitly in VM operations.
podman machine ssh "$machine" 'test "$(uname -m)" = aarch64' ||
  die "Machine is not ARM64"
podman machine ssh "$machine" 'test "$(podman info --format "{{.Host.Security.Rootless}}")" = true' ||
  die "Machine Podman is not rootless"

builder_stores_check podman --connection "$machine"
say "Building the ARM64 image"
podman --connection "$machine" build --platform linux/arm64 -t "$image" "$repo/arm"
if ! podman --connection "$machine" volume exists "$builder_store_volume"; then
  say "Creating empty authoritative Nix store volume"
  builder_volume_create "$scope" "$builder_store_volume" nix-store podman --connection "$machine" >/dev/null
fi
# Set ownership of the volume root only, never recurse through store contents.
builder_store_assert_owner "$scope" "$builder_store_volume" /nix podman --connection "$machine"
# Existing stores are not migrated or repaired and fail closed if unmarked.
podman --connection "$machine" run --rm --pull=never --user 0:0 \
  --mount "type=volume,src=$builder_store_volume,dst=/nix" \
  --entrypoint /bin/sh "$image" -ec '
    if [ -e /nix/.nix-xd-direct-volume-v2 ]; then
      exit 0
    fi
    if [ -n "$(find /nix -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)" ]; then
      echo "Existing unmarked Nix store: explicit redeployment required" >&2
      exit 1
    fi
    chown 1000:1000 /nix
  '
# Optional complete first-start profile, separate from legacy post-bootstrap apply.
initial_chroots="${NIX_XD_INITIAL_CHROOT_STORES:-}"
if [[ -n "$initial_chroots" ]]; then
  [[ ${NIX_XD_INITIAL_PROFILE:-0} == 1 ]] || die 'Initial chroots require INITIAL_PROFILE=1'
  NIX_XD_PEER_STORES='' bash "$repo/bin/nix-xd-builder-profile-prestart" \
    "$machine" "$scope" "$image" "$builder_store_volume" "$initial_chroots"
fi

# First Nix installation occurs only after the final volume is mounted.

say "Installing rootless Quadlet"
printf -v builder_remote_args '%q ' "$scope" "$image" "$builder_store_volume" "${NIX_XD_PEER_STORES:-}" "$initial_chroots" "${NIX_XD_LIFECYCLE:-reusable}" "${NIX_XD_COMPOSITION_ID:-infrastructure}" "${NIX_XD_PLACEMENT_ID:-host}" "${NIX_XD_CHROOT_SELINUX:-keep}"
# The VM's user service manager supervises the container; no macOS daemon needed.
{
cat "$repo/lib/builder-stores.sh"
cat <<'REMOTE' 
set -euo pipefail
scope="$1"
image="$2"
NIX_XD_STORE_VOLUME="$3" NIX_XD_PEER_STORES="$4"
NIX_XD_INITIAL_CHROOT_STORES="${5:-}"
NIX_XD_LIFECYCLE="${6:-reusable}" NIX_XD_COMPOSITION_ID="${7:-infrastructure}" NIX_XD_PLACEMENT_ID="${8:-host}"
NIX_XD_CHROOT_SELINUX="${9:-keep}"
if [[ -n "$NIX_XD_INITIAL_CHROOT_STORES" ]]; then
  NIX_XD_INITIAL_SECCOMP_PATH="$HOME/.config/nix-xd/seccomp/$scope-nix-chroot.json"
fi
builder_stores_init "$scope"
builder_stores_check podman
dir="$HOME/.config/containers/systemd"
mkdir -p "$dir"
file="$dir/$scope.container"
tmp="$(mktemp "$dir/.nix-xd.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
builder_quadlet "$scope" "$image" "Nix-Alpine ARM64 ($scope)" > "$tmp"
if [[ -e "$file" ]]; then
  cmp -s "$tmp" "$file" || { echo "Existing Quadlet differs: $file" >&2; exit 1; }
else
  install -m 600 "$tmp" "$file"
fi
systemctl --user daemon-reload
systemctl --user start "$scope.service"
systemctl --user is-active --quiet "$scope.service"
if [[ "$(loginctl show-user "$USER" -p Linger --value)" != yes ]]; then
  sudo loginctl enable-linger "$USER"
fi
REMOTE
} | podman machine ssh "$machine" "bash -se -- $builder_remote_args"

say "Installing opt-in zsh helper"
mkdir -p "$HOME/.config/nix-xd" "$HOME/Library/Caches/nix-xd"
helper="$HOME/.config/nix-xd/macos.zsh"
if [[ ! -e "$helper" ]]; then
  cat >"$helper" <<'ZSH'
: "${NIX_XD_AUTO_START:=0}"
: "${NIX_XD_MACHINE:=podman-machine-default}"
: "${NIX_XD_SCOPE:=nix-xd-arm}"

nxd-up() {
  local state
  state="$(podman machine inspect "$NIX_XD_MACHINE" --format '{{.State}}' 2>/dev/null)" || return 1
  [[ "$state" == running ]] && return 0
  lockf -t 0 "$HOME/Library/Caches/nix-xd/machine.lock" \
    podman machine start "$NIX_XD_MACHINE"
}
nxd-down() { podman machine stop "$NIX_XD_MACHINE"; }
nxd-status() { podman machine list; }
nxd-shell() { podman exec -it "$NIX_XD_SCOPE" bash -l; }

if [[ -o interactive && "$NIX_XD_AUTO_START" == 1 ]]; then
  nxd-up
fi
ZSH
fi
touch "$HOME/.zshrc"
line='[[ -f "$HOME/.config/nix-xd/macos.zsh" ]] && source "$HOME/.config/nix-xd/macos.zsh"'
grep -Fqx "$line" "$HOME/.zshrc" || printf '\n%s\n' "$line" >>"$HOME/.zshrc"

say "Checking Nix-Alpine bootstrap readiness"
podman machine ssh "$machine" systemctl --user is-active "$unit"
ready=0
for attempt in $(seq 1 120); do
  if podman --connection "$machine" exec "$scope" /bin/sh -ec '
    test -f /nix/.nix-xd-direct-volume-v2
    test -x /nix/home/nixuser/.nix-profile/bin/nix
    /nix/home/nixuser/.nix-profile/bin/nix --version >/dev/null
  ' >/dev/null 2>&1; then
    ready=1
    printf 'NIX_XD_BOOTSTRAP_READY attempts=%s\n' "$attempt"
    break
  fi
  if [[ "$(podman machine ssh "$machine" systemctl --user is-active "$unit" 2>/dev/null)" != active ]]; then
    echo "Nix-Alpine Quadlet became inactive during direct-volume bootstrap" >&2
    break
  fi
  if (( attempt % 12 == 0 )); then
    printf 'NIX_XD_BOOTSTRAP_WAIT attempt=%s\n' "$attempt"
  fi
  sleep 5
done
if [[ "$ready" != 1 ]]; then
  printf '%s\n' '--- Nix-Alpine container logs ---' >&2
  podman --connection "$machine" logs --tail 120 "$scope" >&2 || true
  printf '%s\n' '--- Nix-Alpine user service journal ---' >&2
  podman machine ssh "$machine" journalctl --user --no-pager -u "$unit" -n 120 >&2 || true
  die 'Direct-volume initialization failed or timed out; do not reseed the volume'
fi
podman --connection "$machine" exec "$scope" nix --version
NIX_XD_MACHINE="$machine" NIX_XD_SCOPE="$scope" NIX_XD_IMAGE="$image" \
  COREOS_NIX_STORE_VOLUME="$builder_store_volume" bash "$repo/bin/nix-xd-store-export-check"

printf '\nReady: %s on %s\n' "$unit" "$machine"
printf 'Open a new zsh shell: nxd-status | nxd-up | nxd-shell | nxd-down\n'
printf 'To auto-start on shell open, export NIX_XD_AUTO_START=1 BEFORE sourcing the helper.\n'
