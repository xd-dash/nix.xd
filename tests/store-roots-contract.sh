#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash -n bin/nix-xd-store-roots
sh -n bin/nix-xd-store-root-guest
for arch in arm64 amd64; do
  dry="$(make -sn store-roots-apply ARCH="$arch" PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm)"
  [[ "$dry" == *"bin/nix-xd-log"* && "$dry" == *"bash bin/nix-xd-store-roots apply"* ]] ||
    { echo "Store root apply not logged on $arch" >&2; exit 1; }
done
grep -Fq 'runtime_cmd exec -i --user 0 "$scope" sh -s --' bin/nix-xd-store-roots
grep -Fq 'nix build --no-write-lock-file --no-link --print-out-paths' bin/nix-xd-store-roots
grep -Fq 'mv -fT "$tmp" "$dest"' bin/nix-xd-store-root-guest
grep -Fq 'nix path-info "$path"' bin/nix-xd-store-root-guest
for declaration in 'nix storeProbeNix' 'rootfs storeProbeRootfs' 'dynamic-probe storeProbeDynamic' 'oci-archive storeProbeOciArchive'; do
  grep -Fxq "$declaration" store-roots/starwisp.tsv || { echo "Missing declaration: $declaration" >&2; exit 1; }
done
if grep -Eq 'nix-store --gc|nix store gc|rm -rf /nix|volume rm' bin/nix-xd-store-root-guest bin/nix-xd-store-roots; then
  echo 'Root registration may not garbage collect or reset Nix store' >&2; exit 1
fi
echo 'PASS: Declarative Starwisp GC roots use authenticated volume, registered paths and atomic updates'
