#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n bin/nix-xd-coreos-hvf bin/nix-xd-coreos-podman bin/nix-xd-wisp-ssh bin/nix-xd-qualify-starwisp bin/nix-xd-store-export-check bin/nix-xd-guest-store-exec
for target in coreos-container-build coreos-ignition-build coreos-preflight coreos-boot coreos-stop coreos-qualify coreos-reset-failed qualify-starwisp; do
  result="$(make -sn "$target" COREOS_IMAGE=/tmp/image.qcow2 COREOS_IGNITION=/tmp/config.ign COREOS_FIRMWARE=/tmp/firmware.bin COREOS_SSH_KEY=/tmp/test-key PROFILE=starwisp)"
  [[ "$result" == *"bin/nix-xd-log"* ]] || { echo "Missing CoreOS logger: $target"; exit 1; }
  [[ "$result" == *"bin/nix-xd-"* ]] || { echo "Missing runner script: $target"; exit 1; }
  [[ "$result" == *"bin/nix-xd-log"* ]] || { echo "Missing retained diagnostic logging: $target"; exit 1; }
  if [[ "$target" == coreos-boot ]]; then
    [[ "$result" == *"bin/nix-xd-coreos-podman"* ]] || { echo "Default QEMU provider is not Podman"; exit 1; }
  fi
done
# Test that Make exports the selected values without embedding user paths in
# a shell assignment line. The apostrophe is a regression fixture for quoting.
env_probe="$(make --no-print-directory --silent \
  --eval  COREOS_STATE_ROOT="$(mktemp -d)" COREOS_SSH_PORT=2222 bash bin/nix-xd-coreos-hvf preflight ) >/dev/null 2>&1; then
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
grep -Fq -- '--rootfs "$scratch"' bin/nix-xd-guest-store-exec || { echo "Guest rootfs must be local writable scratch"; exit 1; }
grep -Fq 'scratch="$(mktemp -d "$XDG_RUNTIME_DIR/nix-xd-rootfs.XXXXXXXX")"' bin/nix-xd-guest-store-exec || { echo "Missing disposable runtime rootfs"; exit 1; }
grep -Fq 'ln -s "$store_shell" "$scratch/bin/sh"' bin/nix-xd-guest-store-exec || { echo "Guest helper must use shared-store shell"; exit 1; }
grep -Fq 'ln -s "$store_shell" "$scratch/bin/busybox"' bin/nix-xd-guest-store-exec || { echo "Guest helper must expose BusyBox applets"; exit 1; }
grep -Fq 'COREOS_GUEST_DYNAMIC_EXECUTABLE=' Makefile || { echo "Dynamic executable not propagated"; exit 1; }
grep -Fq 'storeProbeDynamic = pkgs.hello;' flake.nix || { echo "Missing dynamic closure probe"; exit 1; }
grep -Fq 'NIX_9P_DYNAMIC_CLOSURE_EXECUTABLE' bin/nix-xd-wisp-ssh || { echo "Missing dynamic closure runtime check"; exit 1; }
if grep -Fq -- '--rootfs "$probe_rootfs:O"' bin/nix-xd-wisp-ssh; then echo "9P-backed overlay forbidden"; exit 1; fi
grep -Fq 'NIX_9P_NESTED_EXECUTABLE' bin/nix-xd-wisp-ssh || { echo "Missing nested executable qualification"; exit 1; }
if grep -Eq 'podman (save|load)|COREOS_GUEST_PROBE_IMAGE' bin/nix-xd-wisp-ssh; then echo "OCI image copies are forbidden in zero-copy qualification"; exit 1; fi
grep -Fq 'storeProbeOciArchive = pkgs.dockerTools.buildLayeredImage' flake.nix || { echo "Missing cacheable OCI image tarball"; exit 1; }
grep -Fq 'COREOS_GUEST_OCI_ARCHIVE=' Makefile || { echo "Missing OCI archive store path propagation"; exit 1; }
grep -Fq 'NIX_9P_OCI_ARCHIVE_READONLY' bin/nix-xd-wisp-ssh || { echo "Missing read-only OCI archive probe"; exit 1; }
grep -Fq 'nix-9p-oci-archive.log' bin/nix-xd-qualify-starwisp || { echo "Missing OCI archive qualification evidence"; exit 1; }
grep -Fq 'ln -s /proc/self/mounts "$out/etc/mtab"' flake.nix || { echo "Read-only probe rootfs must precreate /etc/mtab"; exit 1; }
grep -Fq 'NIX_9P_ROOTFS_MODE=guest-runtime-scratch' bin/nix-xd-guest-store-exec || { echo "Missing guest-local runtime separation evidence"; exit 1; }
grep -Fq 'NIX_STORE_OWNER_READY' bin/nix-xd-store-export-check || { echo "Missing Nix-Alpine owner mount identity gate"; exit 1; }
grep -Fq 'owner_volume=' bin/nix-xd-store-export-check || { echo "Authoritative store owner volume not checked"; exit 1; }
grep -Fq 'NIX_9P_NIX_CLI_READONLY' bin/nix-xd-wisp-ssh || { echo "Shared Nix CLI execution gate missing"; exit 1; }
grep -Fq 'storeProbeNix = pkgs.nix;' flake.nix || { echo "Nix CLI closure is not declared"; exit 1; }
grep -Fq 'COREOS_GUEST_NIX_EXECUTABLE=' Makefile || { echo "Nix CLI closure path not propagated"; exit 1; }
grep -Fq 'chown 1000:1000 /nix' arm/bootstrap-podman.sh || { echo "New Podman store volume root ownership not initialized"; exit 1; }
grep -Fq 'Existing unmarked Nix store: explicit redeployment required' arm/bootstrap-podman.sh || { echo "Podman legacy store rejection missing"; exit 1; }
grep -Fq 'ENTRYPOINT ["/usr/local/bin/nix-xd-init-store"]' arm/Dockerfile || { echo "ARM image must initialize mounted store at runtime"; exit 1; }
grep -Fq 'NIX_XD_DIRECT_STORE_READY' arm/init-nix-store.sh || { echo "Missing authoritative direct-volume installer"; exit 1; }
grep -Fq 'ENV HOME=/nix/home/nixuser USER=nixuser' arm/Dockerfile || { echo 'Nix home must be on same authoritative volume'; exit 1; }
grep -Fq 'resolved="$(realpath -e "$profile/bin/nix")"' arm/init-nix-store.sh || { echo 'Installer-created profile must resolve to Nix store'; exit 1; }
grep -Fq 'profile="$HOME/.nix-profile"' arm/init-nix-store.sh || { echo "Direct-volume installer must validate installer-created user profile"; exit 1; }
grep -Fq '/nix/home/nixuser/.nix-profile/bin/nix' arm/rebootstrap-podman.sh || { echo "Diagnostics must inspect persistent user profile"; exit 1; }
if grep -Eq 'profiles/per-user/nixuser/profile|profile="\$store/var/nix/profiles/default"' arm/init-nix-store.sh arm/rebootstrap-podman.sh; then echo "Invalid hardcoded installer profile"; exit 1; fi
grep -Fq '.nix-xd-direct-volume-v2' bin/nix-xd-store-export-check || { echo "Legacy image-seeded store must fail closed"; exit 1; }
if grep -Eq 'cp -a /nix/|cp -r /nix/|cp -R /nix/' arm/bootstrap-container.sh arm/bootstrap-podman.sh arm/init-nix-store.sh; then echo "Copying the Nix store is forbidden"; exit 1; fi
if grep -Eq 'RUN.*(install-nix|nix-[0-9].*/install)' arm/Dockerfile; then echo "Building Nix into OCI image store is forbidden"; exit 1; fi
bash -n arm/init-nix-store.sh
grep -Fq 'arm-rebootstrap:' Makefile || { echo 'Missing logged ARM rebootstrap composition'; exit 1; }
grep -Fq 'arm-rebootstrap-plan:' Makefile || { echo 'Missing preflight target'; exit 1; }
grep -Fq 'arm-rebootstrap-reset:' Makefile || { echo 'Missing reset target'; exit 1; }
grep -Fq 'arm-rebootstrap-bootstrap:' Makefile || { echo 'Missing direct volume bootstrap target'; exit 1; }
grep -Fq 'arm-rebootstrap-verify:' Makefile || { echo 'Missing read-only export verification target'; exit 1; }
grep -Fq 'NIX_XD_CONFIRM_RESET' arm/rebootstrap-podman.sh || { echo 'Missing destructive reset confirmation'; exit 1; }
grep -Fq 'volume rm "$volume"' arm/rebootstrap-podman.sh || { echo 'Missing scoped volume reset'; exit 1; }
if grep -Eq '(volume rm -f|volume rm --force|podman system prune)' arm/rebootstrap-podman.sh; then echo 'Forced broad deletion forbidden'; exit 1; fi
grep -Fq 'bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap' Makefile || { echo 'Rebootstrap output must be logged'; exit 1; }
bash -n arm/rebootstrap-podman.sh
grep -Fq 'arm-qualify-recreation:' Makefile || { echo 'Missing modular recreation qualification target'; exit 1; }
grep -Fq 'arm-qualify-recreation bash arm/qualify-recreation-podman.sh' Makefile || { echo 'Recreation must use retained diagnostic log'; exit 1; }
grep -Fq 'qualifiers/modules/store-recreation.sh' arm/qualify-recreation-podman.sh || { echo 'ARM recreation must delegate to shared module'; exit 1; }
grep -Fq 'STORE_RECREATION_CONTAINER_CHANGED=passed' qualifiers/modules/store-recreation.sh || { echo 'Shared recreation must prove new container'; exit 1; }
grep -Fq 'STORE_RECREATION_STORE_PRESERVED=passed' qualifiers/modules/store-recreation.sh || { echo 'Shared recreation must verify store identity'; exit 1; }
grep -Fq 'service restart "$scope.service"' qualifiers/modules/store-recreation.sh || { echo 'Shared recreation must restart systemd user Quadlet'; exit 1; }
grep -Fq 'ARM_RECREATION_RESULT=passed' arm/qualify-recreation-podman.sh || { echo 'Compatibility result marker missing'; exit 1; }
if grep -Eq 'volume (rm|create)|podman (save|load)|nix (build|store gc)' qualifiers/modules/store-recreation.sh; then echo 'Shared recreation must be nondestructive'; exit 1; fi
bash -n arm/qualify-recreation-podman.sh
grep -Fq 'arm-wind-down-plan:' Makefile || { echo 'Missing wind-down plan'; exit 1; }
grep -Fq 'arm-wind-down-stop:' Makefile || { echo 'Missing wind-down stop'; exit 1; }
grep -Fq 'arm-wind-down-stop bash arm/wind-down.sh stop' Makefile || { echo 'Wind-down must retain complete log'; exit 1; }
grep -Fq 'WIND_DOWN_UNINSPECTED_MACHINE=' arm/wind-down.sh || { echo 'Missing unknown machine evidence'; exit 1; }
grep -Fq 'WIND_DOWN_STOP=passed' arm/wind-down.sh || { echo 'Missing stopped status'; exit 1; }
if grep -Eq '(volume rm|machine rm|container delete|container rm|rm -rf)' arm/wind-down.sh; then echo 'Wind-down may not destroy persistent resources'; exit 1; fi
bash -n arm/wind-down.sh
grep -Fq 'arm-inspect-legacy:' Makefile || { echo 'Missing scoped legacy inspection target'; exit 1; }
grep -Fq 'arm-inspect-legacy bash arm/inspect-legacy.sh' Makefile || { echo 'Legacy inspection must retain diagnostic log'; exit 1; }
grep -Fq 'podman machine stop "$machine"' arm/inspect-legacy.sh || { echo 'Legacy inspection must restore stopped state'; exit 1; }
if grep -Eq '(volume rm|machine rm|container delete|container rm|rm -rf)' arm/inspect-legacy.sh; then echo 'Legacy inspection must not delete resources'; exit 1; fi
bash -n arm/inspect-legacy.sh
grep -Fq 'arm-purge-legacy-plan:' Makefile || { echo 'Missing legacy purge planning target'; exit 1; }
grep -Fq 'arm-purge-legacy:' Makefile || { echo 'Missing legacy purge apply target'; exit 1; }
grep -Fq 'ERASE:podman-machine-default:apple-nix-xd-legacy' arm/purge-legacy.sh || { echo 'Missing exact purge confirmation'; exit 1; }
grep -Fq 'podman machine rm --force "$legacy"' arm/purge-legacy.sh || { echo 'Legacy machine must be scoped'; exit 1; }
grep -Fq 'LEGACY_PURGE_RESULT=passed' arm/purge-legacy.sh || { echo 'Missing purge result'; exit 1; }
bash -n arm/purge-legacy.sh
echo "PASS: ARM64 Podman QEMU and repeatable Starwisp qualification contract"
.PHONY: coreos-env-probe\\ncoreos-env-probe: ; @printf "%s|%s|%s\\\\n" "$COREOS_PROFILE" "$COREOS_STATE_ROOT" "$NIX_XD_MACHINE"' \
  coreos-env-probe PROFILE=starwisp MACHINE=coreos-arm64 \
  COREOS_STATE_ROOT="/tmp/starwisp's-fixture")"
[[ "$env_probe" == "starwisp|/tmp/starwisp's-fixture|coreos-arm64" ]] ||
  { echo "CoreOS Make environment export mismatch: $env_probe" >&2; exit 1; }
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
grep -Fq -- '--rootfs "$scratch"' bin/nix-xd-guest-store-exec || { echo "Guest rootfs must be local writable scratch"; exit 1; }
grep -Fq 'scratch="$(mktemp -d "$XDG_RUNTIME_DIR/nix-xd-rootfs.XXXXXXXX")"' bin/nix-xd-guest-store-exec || { echo "Missing disposable runtime rootfs"; exit 1; }
grep -Fq 'ln -s "$store_shell" "$scratch/bin/sh"' bin/nix-xd-guest-store-exec || { echo "Guest helper must use shared-store shell"; exit 1; }
grep -Fq 'ln -s "$store_shell" "$scratch/bin/busybox"' bin/nix-xd-guest-store-exec || { echo "Guest helper must expose BusyBox applets"; exit 1; }
grep -Fq 'COREOS_GUEST_DYNAMIC_EXECUTABLE=' Makefile || { echo "Dynamic executable not propagated"; exit 1; }
grep -Fq 'storeProbeDynamic = pkgs.hello;' flake.nix || { echo "Missing dynamic closure probe"; exit 1; }
grep -Fq 'NIX_9P_DYNAMIC_CLOSURE_EXECUTABLE' bin/nix-xd-wisp-ssh || { echo "Missing dynamic closure runtime check"; exit 1; }
if grep -Fq -- '--rootfs "$probe_rootfs:O"' bin/nix-xd-wisp-ssh; then echo "9P-backed overlay forbidden"; exit 1; fi
grep -Fq 'NIX_9P_NESTED_EXECUTABLE' bin/nix-xd-wisp-ssh || { echo "Missing nested executable qualification"; exit 1; }
if grep -Eq 'podman (save|load)|COREOS_GUEST_PROBE_IMAGE' bin/nix-xd-wisp-ssh; then echo "OCI image copies are forbidden in zero-copy qualification"; exit 1; fi
grep -Fq 'storeProbeOciArchive = pkgs.dockerTools.buildLayeredImage' flake.nix || { echo "Missing cacheable OCI image tarball"; exit 1; }
grep -Fq 'COREOS_GUEST_OCI_ARCHIVE=' Makefile || { echo "Missing OCI archive store path propagation"; exit 1; }
grep -Fq 'NIX_9P_OCI_ARCHIVE_READONLY' bin/nix-xd-wisp-ssh || { echo "Missing read-only OCI archive probe"; exit 1; }
grep -Fq 'nix-9p-oci-archive.log' bin/nix-xd-qualify-starwisp || { echo "Missing OCI archive qualification evidence"; exit 1; }
grep -Fq 'ln -s /proc/self/mounts "$out/etc/mtab"' flake.nix || { echo "Read-only probe rootfs must precreate /etc/mtab"; exit 1; }
grep -Fq 'NIX_9P_ROOTFS_MODE=guest-runtime-scratch' bin/nix-xd-guest-store-exec || { echo "Missing guest-local runtime separation evidence"; exit 1; }
grep -Fq 'NIX_STORE_OWNER_READY' bin/nix-xd-store-export-check || { echo "Missing Nix-Alpine owner mount identity gate"; exit 1; }
grep -Fq 'owner_volume=' bin/nix-xd-store-export-check || { echo "Authoritative store owner volume not checked"; exit 1; }
grep -Fq 'NIX_9P_NIX_CLI_READONLY' bin/nix-xd-wisp-ssh || { echo "Shared Nix CLI execution gate missing"; exit 1; }
grep -Fq 'storeProbeNix = pkgs.nix;' flake.nix || { echo "Nix CLI closure is not declared"; exit 1; }
grep -Fq 'COREOS_GUEST_NIX_EXECUTABLE=' Makefile || { echo "Nix CLI closure path not propagated"; exit 1; }
grep -Fq 'chown 1000:1000 /nix' arm/bootstrap-podman.sh || { echo "New Podman store volume root ownership not initialized"; exit 1; }
grep -Fq 'Existing unmarked Nix store: explicit redeployment required' arm/bootstrap-podman.sh || { echo "Podman legacy store rejection missing"; exit 1; }
grep -Fq 'ENTRYPOINT ["/usr/local/bin/nix-xd-init-store"]' arm/Dockerfile || { echo "ARM image must initialize mounted store at runtime"; exit 1; }
grep -Fq 'NIX_XD_DIRECT_STORE_READY' arm/init-nix-store.sh || { echo "Missing authoritative direct-volume installer"; exit 1; }
grep -Fq 'ENV HOME=/nix/home/nixuser USER=nixuser' arm/Dockerfile || { echo 'Nix home must be on same authoritative volume'; exit 1; }
grep -Fq 'resolved="$(realpath -e "$profile/bin/nix")"' arm/init-nix-store.sh || { echo 'Installer-created profile must resolve to Nix store'; exit 1; }
grep -Fq 'profile="$HOME/.nix-profile"' arm/init-nix-store.sh || { echo "Direct-volume installer must validate installer-created user profile"; exit 1; }
grep -Fq '/nix/home/nixuser/.nix-profile/bin/nix' arm/rebootstrap-podman.sh || { echo "Diagnostics must inspect persistent user profile"; exit 1; }
if grep -Eq 'profiles/per-user/nixuser/profile|profile="\$store/var/nix/profiles/default"' arm/init-nix-store.sh arm/rebootstrap-podman.sh; then echo "Invalid hardcoded installer profile"; exit 1; fi
grep -Fq '.nix-xd-direct-volume-v2' bin/nix-xd-store-export-check || { echo "Legacy image-seeded store must fail closed"; exit 1; }
if grep -Eq 'cp -a /nix/|cp -r /nix/|cp -R /nix/' arm/bootstrap-container.sh arm/bootstrap-podman.sh arm/init-nix-store.sh; then echo "Copying the Nix store is forbidden"; exit 1; fi
if grep -Eq 'RUN.*(install-nix|nix-[0-9].*/install)' arm/Dockerfile; then echo "Building Nix into OCI image store is forbidden"; exit 1; fi
bash -n arm/init-nix-store.sh
grep -Fq 'arm-rebootstrap:' Makefile || { echo 'Missing logged ARM rebootstrap composition'; exit 1; }
grep -Fq 'arm-rebootstrap-plan:' Makefile || { echo 'Missing preflight target'; exit 1; }
grep -Fq 'arm-rebootstrap-reset:' Makefile || { echo 'Missing reset target'; exit 1; }
grep -Fq 'arm-rebootstrap-bootstrap:' Makefile || { echo 'Missing direct volume bootstrap target'; exit 1; }
grep -Fq 'arm-rebootstrap-verify:' Makefile || { echo 'Missing read-only export verification target'; exit 1; }
grep -Fq 'NIX_XD_CONFIRM_RESET' arm/rebootstrap-podman.sh || { echo 'Missing destructive reset confirmation'; exit 1; }
grep -Fq 'volume rm "$volume"' arm/rebootstrap-podman.sh || { echo 'Missing scoped volume reset'; exit 1; }
if grep -Eq '(volume rm -f|volume rm --force|podman system prune)' arm/rebootstrap-podman.sh; then echo 'Forced broad deletion forbidden'; exit 1; fi
grep -Fq 'bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap' Makefile || { echo 'Rebootstrap output must be logged'; exit 1; }
bash -n arm/rebootstrap-podman.sh
grep -Fq 'arm-qualify-recreation:' Makefile || { echo 'Missing modular recreation qualification target'; exit 1; }
grep -Fq 'arm-qualify-recreation bash arm/qualify-recreation-podman.sh' Makefile || { echo 'Recreation must use retained diagnostic log'; exit 1; }
grep -Fq 'qualifiers/modules/store-recreation.sh' arm/qualify-recreation-podman.sh || { echo 'ARM recreation must delegate to shared module'; exit 1; }
grep -Fq 'STORE_RECREATION_CONTAINER_CHANGED=passed' qualifiers/modules/store-recreation.sh || { echo 'Shared recreation must prove new container'; exit 1; }
grep -Fq 'STORE_RECREATION_STORE_PRESERVED=passed' qualifiers/modules/store-recreation.sh || { echo 'Shared recreation must verify store identity'; exit 1; }
grep -Fq 'service restart "$scope.service"' qualifiers/modules/store-recreation.sh || { echo 'Shared recreation must restart systemd user Quadlet'; exit 1; }
grep -Fq 'ARM_RECREATION_RESULT=passed' arm/qualify-recreation-podman.sh || { echo 'Compatibility result marker missing'; exit 1; }
if grep -Eq 'volume (rm|create)|podman (save|load)|nix (build|store gc)' qualifiers/modules/store-recreation.sh; then echo 'Shared recreation must be nondestructive'; exit 1; fi
bash -n arm/qualify-recreation-podman.sh
grep -Fq 'arm-wind-down-plan:' Makefile || { echo 'Missing wind-down plan'; exit 1; }
grep -Fq 'arm-wind-down-stop:' Makefile || { echo 'Missing wind-down stop'; exit 1; }
grep -Fq 'arm-wind-down-stop bash arm/wind-down.sh stop' Makefile || { echo 'Wind-down must retain complete log'; exit 1; }
grep -Fq 'WIND_DOWN_UNINSPECTED_MACHINE=' arm/wind-down.sh || { echo 'Missing unknown machine evidence'; exit 1; }
grep -Fq 'WIND_DOWN_STOP=passed' arm/wind-down.sh || { echo 'Missing stopped status'; exit 1; }
if grep -Eq '(volume rm|machine rm|container delete|container rm|rm -rf)' arm/wind-down.sh; then echo 'Wind-down may not destroy persistent resources'; exit 1; fi
bash -n arm/wind-down.sh
grep -Fq 'arm-inspect-legacy:' Makefile || { echo 'Missing scoped legacy inspection target'; exit 1; }
grep -Fq 'arm-inspect-legacy bash arm/inspect-legacy.sh' Makefile || { echo 'Legacy inspection must retain diagnostic log'; exit 1; }
grep -Fq 'podman machine stop "$machine"' arm/inspect-legacy.sh || { echo 'Legacy inspection must restore stopped state'; exit 1; }
if grep -Eq '(volume rm|machine rm|container delete|container rm|rm -rf)' arm/inspect-legacy.sh; then echo 'Legacy inspection must not delete resources'; exit 1; fi
bash -n arm/inspect-legacy.sh
grep -Fq 'arm-purge-legacy-plan:' Makefile || { echo 'Missing legacy purge planning target'; exit 1; }
grep -Fq 'arm-purge-legacy:' Makefile || { echo 'Missing legacy purge apply target'; exit 1; }
grep -Fq 'ERASE:podman-machine-default:apple-nix-xd-legacy' arm/purge-legacy.sh || { echo 'Missing exact purge confirmation'; exit 1; }
grep -Fq 'podman machine rm --force "$legacy"' arm/purge-legacy.sh || { echo 'Legacy machine must be scoped'; exit 1; }
grep -Fq 'LEGACY_PURGE_RESULT=passed' arm/purge-legacy.sh || { echo 'Missing purge result'; exit 1; }
bash -n arm/purge-legacy.sh
echo "PASS: ARM64 Podman QEMU and repeatable Starwisp qualification contract"
