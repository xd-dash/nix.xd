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
export NIX_XD_WORKSPACE_VERSION=20261111 NIX_XD_WORKSPACE_BASE=main
run() { bash "$repo_root/bin/nix-xd-workspace" "$@"; }
run plan > "$tmp/plan"
[[ ! -e $NIX_XD_WORKSPACE_ROOT ]]
run open > "$tmp/first"
target="$NIX_XD_WORKSPACE_ROOT/source20261111"
[[ $(git -C "$target" branch --show-current) == v20261111 ]]
[[ $(run path) == "$target" ]]
echo changed > "$target/file"
run open > "$tmp/reuse"
grep -qx WORKSPACE_RESULT=reused "$tmp/reuse"
git -C "$target" restore file
git -C "$target" switch -c wrong-date > /dev/null 2>&1
if run open > /dev/null 2>&1; then exit 1; fi
git -C "$target" switch v20261111 > /dev/null 2>&1
NIX_XD_WORKSPACE_VERSION=20261112 run open > /dev/null
[[ -d "$NIX_XD_WORKSPACE_ROOT/source20261112/.git" ]]
[[ $(git -C "$target" branch --show-current) == v20261111 ]]
for bad in ../bad 20260231 20261301; do
  if NIX_XD_WORKSPACE_VERSION="$bad" run open > /dev/null 2>&1; then exit 1; fi
done
mkdir "$target.lock"
if run open > /dev/null 2>&1; then exit 1; fi
rmdir "$target.lock"
git -C "$target" remote set-url origin file:///wrong
if run open > /dev/null 2>&1; then exit 1; fi
git -C "$tmp/source" branch v20261113
NIX_XD_WORKSPACE_VERSION=20261113 NIX_XD_WORKSPACE_BASE=v20261113 run open > /dev/null
[[ $(git -C "$NIX_XD_WORKSPACE_ROOT/source20261113" branch --show-current) == v20261113 ]]
mkdir -p "$NIX_XD_WORKSPACE_ROOT/source" "$NIX_XD_WORKSPACE_ROOT/source-fresh" "$NIX_XD_WORKSPACE_ROOT/source-consolidated"
mkdir -p "$NIX_XD_WORKSPACE_ROOT/grumble" "$NIX_XD_WORKSPACE_ROOT/source-tools" "$NIX_XD_WORKSPACE_ROOT/source20261201"
echo stale > "$NIX_XD_WORKSPACE_ROOT/source/file"
git -C "$tmp/source" worktree add --quiet --detach "$NIX_XD_WORKSPACE_ROOT/source20261110" HEAD
if (cd "$NIX_XD_WORKSPACE_ROOT/source"; NIX_XD_WORKSPACE_VERSION=20261113 run clean-plan > /dev/null 2>&1); then exit 1; fi
NIX_XD_WORKSPACE_VERSION=20261113 run clean-plan > "$tmp/cleanup-plan"
[[ -f "$NIX_XD_WORKSPACE_ROOT/source/file" ]]
grep -qx "WORKSPACE_REMOVE=$NIX_XD_WORKSPACE_ROOT/source" "$tmp/cleanup-plan"
NIX_XD_WORKSPACE_VERSION=20261113 run clean > "$tmp/cleanup"
for stale in source source-fresh source-consolidated source20261110 source20261111 source20261112; do
  [[ ! -e $NIX_XD_WORKSPACE_ROOT/$stale ]]
done
if git -C "$tmp/source" worktree list --porcelain | grep -Fq "$NIX_XD_WORKSPACE_ROOT/source20261110"; then exit 1; fi
for keep in source20261113 source20261201 source-tools grumble; do
  [[ -d $NIX_XD_WORKSPACE_ROOT/$keep ]]
done
if NIX_XD_WORKSPACE_VERSION=20261114 run clean > /dev/null 2>&1; then exit 1; fi
echo WORKSPACE_CONTRACT=passed
