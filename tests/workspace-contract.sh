#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/.." && pwd -P)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git init -q "$tmp/source"
git -C "$tmp/source" config user.name Fixture
git -C "$tmp/source" config user.email fixture@example.invalid
printf 'fixture\n' > "$tmp/source/file"
git -C "$tmp/source" add file
git -C "$tmp/source" commit -qm initial
git -C "$tmp/source" branch -M main
git init -q --bare "$tmp/remote.git"
git -C "$tmp/remote.git" symbolic-ref HEAD refs/heads/main
git -C "$tmp/source" remote add origin "$tmp/remote.git"
git -C "$tmp/source" push -q origin main
export NIX_XD_WORKSPACE_ROOT="$tmp/workspaces"
export NIX_XD_WORKSPACE_REPO="file://$tmp/remote.git"
export NIX_XD_WORKSPACE_VERSION=20261113.0
export NIX_XD_WORKSPACE_BASE=main
run() { python3 "$root/bin/nix-xd-workspace" "$@"; }
run plan > "$tmp/plan"
[[ ! -d $NIX_XD_WORKSPACE_ROOT ]]
run init > /dev/null
run open > "$tmp/first"
one="$NIX_XD_WORKSPACE_ROOT/remote20261113.0"
[[ $(git -C "$one" branch --show-current) == cal/0.20261113.0 ]]
[[ -f "$one/.git" ]]
[[ $(git -C "$one" rev-parse --git-common-dir | xargs realpath) == "$(realpath "$NIX_XD_WORKSPACE_ROOT/.repos/remote.git")" ]]
run open > "$tmp/reuse"
grep -q WORKSPACE_RESULT=reused "$tmp/reuse"
NIX_XD_WORKSPACE_VERSION=20261113.0 run refresh > "$tmp/second"
two="$NIX_XD_WORKSPACE_ROOT/remote20261113.1"
[[ -f "$two/.git" ]]
[[ $(git -C "$two" branch --show-current) == cal/0.20261113.1 ]]
[[ $(git -C "$one" rev-parse --git-common-dir) == "$(git -C "$two" rev-parse --git-common-dir)" ]]
if run clean >/dev/null 2>&1; then exit 1; fi
if run remove >/dev/null 2>&1; then exit 1; fi
[[ -d $one && -d $two ]]
for invalid in 20260231.0 20261113 20261113.01 ../bad; do
  if NIX_XD_WORKSPACE_VERSION="$invalid" run plan >/dev/null 2>&1; then exit 1; fi
done
[[ $(run list | grep -c ^worktree) == 3 ]]
echo WORKSPACE_CONTRACT=passed
