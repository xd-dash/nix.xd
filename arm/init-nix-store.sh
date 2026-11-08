#!/usr/bin/env bash
set -Eeuo pipefail

: "${NIX_XD_NIX_VERSION:=2.31.2}"
store=/nix
marker="$store/.nix-xd-direct-volume-v2"
profile="$HOME/.nix-profile"
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" == 1000 ]] || fail 'Nix store installer must run as nixuser (UID 1000)'
[[ "$HOME" == /nix/home/nixuser ]] || fail 'HOME must reside in the authoritative /nix volume'
[[ -d "$store" && -w "$store" ]] || fail 'Persistent /nix mount missing or not writable'
grep -Eq ' /nix rw(,| )' /proc/self/mountinfo ||
  fail 'Refusing initialization without writable /nix mount'

if [[ ! -e "$marker" ]]; then
  [[ -z "$(find "$store" -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)" ]] ||
    fail 'Existing unmarked store: clean rebootstrap required; refusing migration or copying'
  mkdir -p "$HOME/.config/nix"
  cp /etc/nix-xd/nix.conf "$HOME/.config/nix/nix.conf"
  installer="$(mktemp)"
  trap 'rm -f -- "$installer"' EXIT
  curl --fail --show-error --location     "https://releases.nixos.org/nix/nix-${NIX_XD_NIX_VERSION}/install" -o "$installer"
  sh "$installer" --no-daemon --yes || fail 'Direct-volume Nix installation failed'
  [[ -x "$profile/bin/nix" ]] || fail 'Installer did not create an executable user profile'
  resolved="$(realpath -e "$profile/bin/nix")" || fail 'Installed Nix executable is not resolvable'
  [[ "$resolved" == /nix/store/* ]] || fail 'Nix profile does not resolve into the mounted store'
  "$profile/bin/nix" --version
  "$profile/bin/nix" store info >/dev/null
  touch "$marker"
fi

[[ -x "$profile/bin/nix" ]] || fail 'Persisted Nix profile executable missing'
resolved="$(realpath -e "$profile/bin/nix")" || fail 'Persisted Nix executable cannot resolve'
[[ "$resolved" == /nix/store/* ]] || fail 'Persisted profile points outside the authoritative store'
export PATH="$profile/bin:$PATH"
nix --version
nix store info >/dev/null
printf 'NIX_XD_DIRECT_STORE_READY path=/nix profile=%s version=%s\n' "$profile" "$(nix --version)"
exec "$@"
