#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n bin/nix-xd-coreos-hvf bin/nix-xd-coreos-podman bin/nix-xd-wisp-ssh bin/nix-xd-qualify-starwisp
for target in coreos-container-build coreos-ignition-build coreos-preflight coreos-boot coreos-stop coreos-qualify coreos-reset-failed qualify-starwisp; do
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
grep -Fq 'COREOS_ORPHANED_OVERLAY=' Makefile || { echo "Missing orphan-reset Make environment"; exit 1; }
grep -Fq '[[ "$source_machine" != "$machine" ]]' bin/nix-xd-coreos-podman || { echo "Missing cross-machine reset fence"; exit 1; }
grep -Fq 'Original machine $source_machine is still running' bin/nix-xd-coreos-podman || { echo "Missing original machine stop fence"; exit 1; }
grep -Fq 'step preflight bash "$adapter" preflight' bin/nix-xd-qualify-starwisp || { echo "Preflight must invoke non-executable adapter with bash"; exit 1; }
grep -Fq 'step wisp-qualification bash "$qualifier"' bin/nix-xd-qualify-starwisp || { echo "Wisp qualifier must run through bash"; exit 1; }
grep -Fq 'COREOS_READY_TIMEOUT_SEC=' Makefile || { echo "Missing readiness configuration"; exit 1; }
grep -Fq 'SSH_WAIT profile=' bin/nix-xd-wisp-ssh || { echo "Missing readiness progress"; exit 1; }
grep -Fq 'trap cleanup EXIT' bin/nix-xd-qualify-starwisp || { echo "Missing qualification cleanup"; exit 1; }
grep -Fq 'runner_id=%s' bin/nix-xd-qualify-starwisp || { echo "Missing runner provenance"; exit 1; }
grep -Fq 'disk_sha256=%s' bin/nix-xd-qualify-starwisp || { echo "Missing disk provenance"; exit 1; }
grep -Fq 'wisp_log_sha256=%s' bin/nix-xd-qualify-starwisp || { echo "Missing Wisp evidence hash"; exit 1; }
grep -Fq 'step archive-previous bash "$adapter" reset-failed' bin/nix-xd-qualify-starwisp || { echo "Missing prior-run archival"; exit 1; }
echo "PASS: ARM64 Podman QEMU and repeatable Starwisp qualification contract"
