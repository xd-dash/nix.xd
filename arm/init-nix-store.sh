#!/usr/bin/env bash
set -Eeuo pipefail

: "${NIX_XD_NIX_VERSION:=2.31.2}"
store=/nix
marker="$store/.nix-xd-direct-volume-v1"
profile="$store/var/nix/profiles/per-user/nixuser/profile"
fail() { printf "error: %s\n" "$*" >&2; exit 1; }
[[ "$(id -u)" == 1000 ]] || fail "Nix store installer must run as nixuser (UID 1000)"
[[ -d "$store" && -w "$store" ]] || fail "Persistent /nix mount is missing or not writable"
grep -Eq " /nix rw(,| )" /proc/self/mountinfo || fail "Refusing to initialize without a writable /nix mount"

if [[ ! -e "$marker" ]]; then
  [[ -z "$(find "$store" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
    fail "Existing unmarked store: refusing to copy, overwrite, or migrate; re-provision explicitly"
  installer="$(mktemp)"
  trap 'rm -f -- "$installer"' EXIT
  curl --fail --show-error --location "https://releases.nixos.org/nix/nix-${NIX_XD_NIX_VERSION}/install" -o "$installer"
  sh "$installer" --no-daemon --yes || fail "Direct-volume Nix installation failed"
  [[ -x "$profile/bin/nix" ]] || fail "Nix profile missing following installation"
  "$profile/bin/nix" --version
  touch "$marker"
fi

[[ -x "$profile/bin/nix" ]] || fail "Initialized store has no persistent Nix profile"
if [[ ! -e "$HOME/.nix-profile" && ! -L "$HOME/.nix-profile" ]]; then
  ln -s "$profile" "$HOME/.nix-profile"
fi
[[ "$(readlink "$HOME/.nix-profile")" == "$profile" ]] ||
  fail "Home profile points away from persistent Nix store"
export PATH="$HOME/.nix-profile/bin:$PATH"
nix --version
nix store info >/dev/null
printf "NIX_XD_DIRECT_STORE_READY path=/nix profile=%s\n" "$profile"
exec "$@"
