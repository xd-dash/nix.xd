#!/usr/bin/env bash
set -Eeuo pipefail
command -v nix-store >/dev/null
command -v nix-instantiate >/dev/null
test_dir="$(mktemp -d)"
trap 'rm -rf -- "$test_dir"' EXIT
store="local?root=$test_dir"
export NIX_CONFIG='build-users-group = '
nix_store() { nix-store --store "$store" "$@"; }
realize_text() {
  nix-instantiate --store "$store" --eval --read-write-mode --expr "$1" | tr -d '"'
}
rooted="$(realize_text 'let dep = builtins.toFile "gc-dependency" "dependency survives\n"; in builtins.toFile "gc-rooted" "${dep}\n"')"
dependency="$(nix_store --query --references "$rooted")"
unrooted="$(realize_text 'builtins.toFile "gc-unrooted" "collect me\n"')"
[[ "$dependency" == /nix/store/* && "$dependency" != *$'\n'* ]]
root_dir="$test_dir/nix/var/nix/gcroots/nix-xd/starwisp"
mkdir -p "$root_dir"
ln -s "$rooted" "$root_dir/rootfs"
nix_store --version
printf 'DISPOSABLE_STORE=%s\n' "$store"
nix_store --gc --print-roots | tee "$test_dir/roots.txt"
grep -Fq -- "-> $rooted" "$test_dir/roots.txt"
nix_store --gc
[[ -f "$test_dir$rooted" && -f "$test_dir$dependency" ]]
[[ ! -e "$test_dir$unrooted" ]]
[[ "$(cat "$test_dir$rooted")" == "$dependency" ]]
[[ "$(cat "$test_dir$dependency")" == 'dependency survives' ]]
nix_store --check-validity "$rooted" "$dependency"
printf 'PASS: rooted output and dependency retained; unrooted control collected\n'
rm "$root_dir/rootfs"
nix_store --gc
[[ ! -e "$test_dir$rooted" && ! -e "$test_dir$dependency" ]]
printf 'PASS: output and dependency collected after removing root\n'
printf 'STORE_ROOTS_GC_RESULT=passed\n'
