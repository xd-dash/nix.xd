#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n bin/nix-xd-coreos-hvf bin/nix-xd-coreos-podman bin/nix-xd-wisp-ssh
for target in coreos-container-build coreos-ignition-build coreos-preflight coreos-boot coreos-stop coreos-qualify coreos-reset-failed; do
  result="$(make -sn "$target" COREOS_IMAGE=/tmp/image.qcow2 COREOS_IGNITION=/tmp/config.ign COREOS_FIRMWARE=/tmp/firmware.bin COREOS_SSH_KEY=/tmp/test-key PROFILE=starwisp)"
  [[ "$result" == *"COREOS_PROFILE='starwisp'"* ]] || { echo "Missing profile propagation: $target"; exit 1; }
  [[ "$result" == *"bin/nix-xd-"* ]] || { echo "Missing runner script: $target"; exit 1; }
  [[ "$result" == *"bin/nix-xd-log"* ]] || { echo "Missing retained diagnostic logging: $target"; exit 1; }
  if [[ "$target" == coreos-boot ]]; then
    [[ "$result" == *"bin/nix-xd-coreos-podman"* ]] || { echo "Default QEMU provider is not Podman"; exit 1; }
  fi
done
if ( COREOS_PROFILE="bad/name" COREOS_STATE_ROOT="$(mktemp -d)" COREOS_SSH_PORT=2222 bash bin/nix-xd-coreos-hvf preflight ) >/dev/null 2>&1; then
  echo "Invalid profile was accepted" >&2; exit 1
fi
grep -Fq 'COREOS_STARWISP_BUTANE="$butane"' bin/nix-xd-coreos-podman || { echo "Agni Butane source not passed into flake"; exit 1; }
grep -Fq 'ram="${COREOS_RAM_MIB:-2048}"' bin/nix-xd-coreos-podman || { echo "Missing configurable RAM"; exit 1; }
grep -Fq '  reset-failed) reset_failed ;;' bin/nix-xd-coreos-podman || { echo "Missing failed guest archival action"; exit 1; }
echo "PASS: ARM64 Podman QEMU, Starwisp source routing, configurable RAM and failed-state archival"
