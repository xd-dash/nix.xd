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
image="localhost/nix-xd:arm64"
unit="$scope.service"

command -v podman >/dev/null 2>&1 || die "Install Podman first: brew install podman"

if ! podman machine inspect "$machine" >/dev/null 2>&1; then
  say "Creating rootless Podman Machine: $machine"
  podman machine init --provider applehv \
    --cpus "${NIX_XD_CPUS:-6}" \
    --memory "${NIX_XD_MEMORY_MIB:-12288}" \
    --disk-size "${NIX_XD_DISK_GIB:-120}" \
    --rootful=false "$machine"
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

say "Building the ARM64 image"
podman build --platform linux/arm64 -t "$image" "$repo/arm"
podman run --rm "$image" nix --version
podman volume exists "$scope-store" || podman volume create "$scope-store" >/dev/null

say "Installing rootless Quadlet"
# The VM's user service manager supervises the container; no macOS daemon needed.
podman machine ssh "$machine" bash -se -- "$scope" "$image" <<'REMOTE'
set -euo pipefail
scope="$1"
image="$2"
dir="$HOME/.config/containers/systemd"
mkdir -p "$dir"
file="$dir/$scope.container"
tmp="$(mktemp "$dir/.nix-xd.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
cat >"$tmp" <<EOF
[Unit]
Description=Nix-Alpine ARM64 ($scope)

[Container]
Image=$image
ContainerName=$scope
Pull=never
Volume=$scope-store:/nix
Exec=sleep infinity

[Service]
Restart=on-failure
TimeoutStartSec=300

[Install]
WantedBy=default.target
EOF
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

say "Checking service"
podman machine ssh "$machine" systemctl --user is-active "$unit"
podman exec "$scope" nix --version

printf '\nReady: %s on %s\n' "$unit" "$machine"
printf 'Open a new zsh shell: nxd-status | nxd-up | nxd-shell | nxd-down\n'
printf 'To auto-start on shell open, export NIX_XD_AUTO_START=1 BEFORE sourcing the helper.\n'
