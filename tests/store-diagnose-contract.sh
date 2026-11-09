#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash -n bin/nix-xd-task
sh -n bin/nix-xd-store-diagnose
for arch in arm64 amd64; do
  dry="$(make -sn store-diagnose ARCH="$arch" PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm)"
  [[ "$dry" == *"bin/nix-xd-log"* && "$dry" == *"store-diagnose bash bin/nix-xd-task store-diagnose"* ]] ||
    { echo "Missing logged store diagnosis on $arch" >&2; exit 1; }
done
grep -Fq 'store-diagnose) inside sh -s <' bin/nix-xd-task
grep -Fq 'STORE_DIAG_RESULT=passed' bin/nix-xd-store-diagnose
grep -Fq 'nix path-info --all' bin/nix-xd-store-diagnose
grep -Fq 'nix-store --gc --print-roots' bin/nix-xd-store-diagnose
if grep -Eq 'nix (build|store gc|store delete)|podman (cp|load|save)|rm -rf /nix' bin/nix-xd-store-diagnose; then
  echo 'Inventory diagnostics may not mutate the store' >&2
  exit 1
fi
echo 'PASS: Read-only shared Nix store inventory is logged through common runtime adapter'
