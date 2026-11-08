#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n bin/nix-xd-coreos-hvf bin/nix-xd-wisp-ssh
for target in coreos-container-build coreos-ignition-build coreos-preflight coreos-boot coreos-stop coreos-qualify; do
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
echo "PASS: ARM64 Podman QEMU and optional HVF Make routing, fail-closed profile validation"
