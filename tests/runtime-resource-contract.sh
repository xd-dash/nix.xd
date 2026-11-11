#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
bash -n "$repo/bin/nix-xd-runtime-inventory" "$repo/bin/nix-xd-image-export" "$repo/bin/nix-xd-log"
mkdir -p "$tmp/repo/bin"
cp "$repo/bin/nix-xd-log" "$tmp/repo/bin/"
(
  unset NIX_XD_LOG_DIR
  export NIX_XD_LOG_COMPOSITION=fixture NIX_XD_LOG_MACHINE=vm1
  export NIX_XD_LOG_PLACEMENT=guest NIX_XD_LOG_CONTAINER=reader
  set +e
  bash "$tmp/repo/bin/nix-xd-log" test action bash -c 'echo fixture; exit 7' > "$tmp/output"
  rc=$?
  set -e
  [[ $rc == 7 ]]
  files=("$tmp/repo/.logs/"test-action--fixture--vm1--guest--reader-*.log)
  [[ ${#files[@]} == 1 && -f ${files[0]} ]]
  grep -qx fixture "${files[0]}"
)
NIX_XD_LOG_DIR="$tmp/shared" bash "$tmp/repo/bin/nix-xd-log" test override true > /dev/null
[[ -d "$tmp/shared" ]]
source "$repo/lib/builder-stores.sh"
unset NIX_XD_PEER_STORES NIX_XD_STORE_VOLUME NIX_XD_INITIAL_CHROOT_STORES
export NIX_XD_LIFECYCLE=reusable NIX_XD_COMPOSITION_ID=fixture NIX_XD_PLACEMENT_ID=host
builder_stores_init test
builder_quadlet test localhost/test:arm64 Test > "$tmp/quadlet"
grep -qx 'Label=io.nix-xd.managed=true' "$tmp/quadlet"
grep -qx 'Label=io.nix-xd.scope=test' "$tmp/quadlet"
grep -qx 'Label=io.nix-xd.lifecycle=reusable' "$tmp/quadlet"
grep -qx 'Volume=test-store:/nix' "$tmp/quadlet"
NIX_XD_LIFECYCLE=disposable builder_quadlet test localhost/test:arm64 Test > "$tmp/disposable"
grep -qx 'Label=io.nix-xd.lifecycle=disposable' "$tmp/disposable"
if NIX_XD_LIFECYCLE=invalid builder_quadlet test localhost/test:arm64 Test > /dev/null; then exit 1; fi
fake_cli() { printf '%s\n' "$@" > "$tmp/create"; }
builder_volume_create test test-store nix-store fake_cli
grep -qx 'io.nix-xd.managed=true' "$tmp/create"
grep -qx 'io.nix-xd.lifecycle=reusable' "$tmp/create"
[[ $(tail -n 1 "$tmp/create") == test-store ]]
echo RUNTIME_RESOURCE_CONTRACT=passed
