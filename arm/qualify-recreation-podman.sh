#!/usr/bin/env bash
set -Eeuo pipefail
# Compatibility entrypoint; architecture-neutral qualification lives in one module.
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export NIX_XD_PROVIDER=podman
export NIX_XD_SYSTEM=aarch64-linux
bash "$repo/qualifiers/modules/store-recreation.sh"
printf 'ARM_RECREATION_RESULT=passed machine=%s scope=%s volume=%s\n' \
  "${NIX_XD_MACHINE:-podman-machine-default}" "${NIX_XD_SCOPE:-nix-xd-arm}" "${NIX_XD_SCOPE:-nix-xd-arm}-store"
