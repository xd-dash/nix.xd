#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash -n bin/nix-xd-store-isolation
dry="$(make -sn store-isolation-check ARCH=arm64 PROVIDER=container)"
[[ "$dry" == *"bin/nix-xd-store-isolation"* ]] || exit 1
grep -Fq 'STORE_ISOLATION_RESULT=passed' bin/nix-xd-store-isolation
grep -Fq 'NIX_XD_ISOLATION_PRIMARY' bin/nix-xd-store-isolation
grep -Fq 'NIX_XD_ISOLATION_SECONDARY' bin/nix-xd-store-isolation
! grep -Eq 'volume (rm|delete)|nix store gc|nix-store --gc|rm -rf /nix' bin/nix-xd-store-isolation
echo 'PASS: isolated stores use separate scope volumes and read-only preflight'
