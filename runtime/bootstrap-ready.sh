#!/usr/bin/env bash
set -euo pipefail
flake=${1:?Staged runtime flake required}
shift
[[ $(id -u) == 1000 ]]
test -f /nix/.nix-xd-direct-volume-v2
grep -Eq '^CapEff:[[:space:]]+0+$' /proc/self/status
grep -Eq '^Seccomp:[[:space:]]+2$' /proc/self/status
for root in "$@"; do
  test -w "$root"
  test -f "$root/.nix-xd-chroot-v1"
  test "$(stat -c %u:%g "$root")" = 1000:1000
done
roots=/nix/var/nix/gcroots/nix-xd/bootstrap-profile
mkdir -p "$roots"
printf 'BOOTSTRAP_CAPABILITY_CHECK=building-tools\n'
tools=$(nix build --store local --no-write-lock-file --print-out-paths \
  --out-link "$roots/tools" "$flake#bootstrapProfileTools")
"$tools/bin/nix-xd-proc-probe"
"$tools/bin/nix-xd-builder-policy" probe
printf 'BOOTSTRAP_CAPABILITY_CHECK=passed private_proc=true private_uts=true\n'
