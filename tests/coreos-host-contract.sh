#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n bin/nix-xd-coreos-hvf bin/nix-xd-coreos-podman bin/nix-xd-wisp-ssh bin/nix-xd-qualify-starwisp bin/nix-xd-store-export-check
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
grep -Fq 'COREOS_NIX_STORE_VOLUME=' Makefile || { echo "Missing host 9P volume propagation"; exit 1; }
grep -Fq 'type=volume,src=$store_volume,dst=/host-nix,ro' bin/nix-xd-coreos-podman || { echo "Nix share not read-only"; exit 1; }
grep -Fq 'qemu_mode=run-shared-nix' bin/nix-xd-coreos-podman || { echo "9P device not delegated to Agni"; exit 1; }
grep -Fq 'Shared Nix store option does not match the built Ignition configuration' bin/nix-xd-coreos-podman || { echo "Missing Ignition export fence"; exit 1; }
grep -Fq '/proc/self/mountinfo' bin/nix-xd-store-export-check || { echo "Missing kernel read-only mount verification"; exit 1; }
if grep -Fq 'test ! -w /host-nix/store' bin/nix-xd-store-export-check; then
  echo "Root write-access heuristic must not be used for read-only mount verification"; exit 1
fi
grep -Fq 'NIX_STORE_EXPORT_READY' bin/nix-xd-store-export-check || { echo "Missing permission verification"; exit 1; }
grep -Fq 'nix-xd-store-export-check' arm/bootstrap-podman.sh || { echo "Bootstrap does not verify volume export"; exit 1; }
grep -Fq 'COREOS_READY_TIMEOUT_SEC=' Makefile || { echo "Missing readiness configuration"; exit 1; }
grep -Fq 'SSH_WAIT profile=' bin/nix-xd-wisp-ssh || { echo "Missing readiness progress"; exit 1; }
grep -Fq 'trap cleanup EXIT' bin/nix-xd-qualify-starwisp || { echo "Missing qualification cleanup"; exit 1; }
grep -Fq 'runner_id=%s' bin/nix-xd-qualify-starwisp || { echo "Missing runner provenance"; exit 1; }
grep -Fq 'disk_sha256=%s' bin/nix-xd-qualify-starwisp || { echo "Missing disk provenance"; exit 1; }
grep -Fq 'wisp_log_sha256=%s' bin/nix-xd-qualify-starwisp || { echo "Missing Wisp evidence hash"; exit 1; }
grep -Fq 'step archive-previous bash "$adapter" reset-failed' bin/nix-xd-qualify-starwisp || { echo "Missing prior-run archival"; exit 1; }
grep -Fq 'COREOS_CONTAINER_NAME=' Makefile || { echo "Missing isolated guest name propagation"; exit 1; }
grep -Fq 'scope_name="${COREOS_CONTAINER_NAME:-coreos-$profile}"' bin/nix-xd-wisp-ssh || { echo "SSH qualifier does not select isolated guest"; exit 1; }
grep -Fq 'shared_nix_volume=%s' bin/nix-xd-coreos-podman || { echo "Ignition exporter does not record 9P source"; exit 1; }
grep -Fq 'NIX_9P_GUEST_MOUNT' bin/nix-xd-wisp-ssh || { echo "Guest 9P mount is unqualified"; exit 1; }
grep -Fq 'NIX_9P_NESTED_PODMAN_READONLY' bin/nix-xd-wisp-ssh || { echo "Nested Podman gate missing"; exit 1; }
grep -Fq 'nix-9p-nested.log' bin/nix-xd-qualify-starwisp || { echo "Nested Podman evidence missing"; exit 1; }
grep -Fq 'COREOS_GUEST_PROBE_ROOTFS=' Makefile || { echo "Missing shared rootfs propagation"; exit 1; }
grep -Fq 'storeProbeRootfs = pkgs.runCommand' flake.nix || { echo "Missing Nix store rootfs probe"; exit 1; }
grep -Fq -- '--rootfs "$probe_rootfs:O"' bin/nix-xd-wisp-ssh || { echo "Nested Podman must use disposable overlay on shared store"; exit 1; }
grep -Fq -- '--mount type=bind,src=/var/mnt/nixstore,dst=/nix/store,ro' bin/nix-xd-wisp-ssh || { echo "Nested Podman must mount shared store read-only"; exit 1; }
grep -Fq 'NIX_9P_NESTED_EXECUTABLE' bin/nix-xd-wisp-ssh || { echo "Missing nested executable qualification"; exit 1; }
if grep -Eq 'podman (save|load)|COREOS_GUEST_PROBE_IMAGE' bin/nix-xd-wisp-ssh; then echo "OCI image copies are forbidden in zero-copy qualification"; exit 1; fi
grep -Fq 'storeProbeOciArchive = pkgs.dockerTools.buildLayeredImage' flake.nix || { echo "Missing cacheable OCI image tarball"; exit 1; }
grep -Fq 'COREOS_GUEST_OCI_ARCHIVE=' Makefile || { echo "Missing OCI archive store path propagation"; exit 1; }
grep -Fq 'NIX_9P_OCI_ARCHIVE_READONLY' bin/nix-xd-wisp-ssh || { echo "Missing read-only OCI archive probe"; exit 1; }
grep -Fq 'nix-9p-oci-archive.log' bin/nix-xd-qualify-starwisp || { echo "Missing OCI archive qualification evidence"; exit 1; }
grep -Fq 'ln -s /proc/self/mounts "$out/etc/mtab"' flake.nix || { echo "Read-only probe rootfs must precreate /etc/mtab"; exit 1; }
grep -Fq 'test -f /run/.containerenv' bin/nix-xd-wisp-ssh || { echo "Missing disposable OCI runtime state verification"; exit 1; }
echo "PASS: ARM64 Podman QEMU and repeatable Starwisp qualification contract"
