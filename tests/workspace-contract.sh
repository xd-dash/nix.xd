#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
git init -q "$tmp/source"
git -C "$tmp/source" config user.name Fixture
git -C "$tmp/source" config user.email fixture@example.invalid
echo initial > "$tmp/source/file"
git -C "$tmp/source" add file
git -C "$tmp/source" commit -qm initial
git -C "$tmp/source" branch -M main
export NIX_XD_WORKSPACE_ROOT="$tmp/work spaces"
export NIX_XD_WORKSPACE_REPO="file://$tmp/source"
export NIX_XD_WORKSPACE_VERSION=20261111 NIX_XD_WORKSPACE_TOPIC=work NIX_XD_WORKSPACE_BASE=main
run() { bash "$repo_root/bin/nix-xd-workspace" "$@"; }
run plan > "$tmp/plan"
[[ ! -e $NIX_XD_WORKSPACE_ROOT ]]
run open > "$tmp/first"
target="$NIX_XD_WORKSPACE_ROOT/source20261111"
[[ $(git -C "$target" branch --show-current) == work/20261111/work ]]
[[ $(run path) == "$target" ]]
echo changed > "$target/file"
run open > "$tmp/reuse"
grep -qx WORKSPACE_RESULT=reused "$tmp/reuse"
if NIX_XD_WORKSPACE_TOPIC=other run open > /dev/null 2>&1; then exit 1; fi
git -C "$target" restore file
NIX_XD_WORKSPACE_TOPIC=other run open > /dev/null
[[ $(git -C "$target" branch --show-current) == work/20261111/other ]]
NIX_XD_WORKSPACE_VERSION=20261112 run open > /dev/null
[[ -d "$NIX_XD_WORKSPACE_ROOT/source20261112/.git" ]]
[[ $(git -C "$target" branch --show-current) == work/20261111/other ]]
for bad in ../bad 20260231 20261301; do
  if NIX_XD_WORKSPACE_VERSION="$bad" run open > /dev/null 2>&1; then exit 1; fi
done
mkdir "$target.lock"
if run open > /dev/null 2>&1; then exit 1; fi
rmdir "$target.lock"
git -C "$target" remote set-url origin file:///wrong
if run open > /dev/null 2>&1; then exit 1; fi
echo WORKSPACE_CONTRACT=passed
