#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n bin/nix-xd-qualify-starwisp-shared
dry="$(make -sn qualify-starwisp-shared ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm COREOS_SSH_KEY=/tmp/key)"
[[ "$dry" == *'COREOS_PROBE_FLAKE='* && "$dry" == *'bin/nix-xd-qualify-starwisp-shared'* ]] ||
  { echo 'Missing shared Starwisp preparation dispatch' >&2; exit 1; }
for output in storeProbeRootfs storeProbeDynamic storeProbeNix storeProbeOciArchive; do
  grep -Fq "build_probe $output" bin/nix-xd-qualify-starwisp-shared ||
    { echo "Missing current-store probe $output" >&2; exit 1; }
done
grep -Fq '"$flake#$name^out"' bin/nix-xd-qualify-starwisp-shared || {
  echo 'Multi-output Nix packages must select the executable out output' >&2
  exit 1
}
grep -Fq 'shared_nix_volume=' bin/nix-xd-qualify-starwisp-shared
grep -Fq 'COREOS_NIX_STORE_VOLUME="$store_volume"' bin/nix-xd-qualify-starwisp-shared
grep -Fq 'NIX_XD_MACHINE="$machine"' bin/nix-xd-qualify-starwisp-shared
grep -Fq 'COREOS_GUEST_PROBE_ROOTFS="$rootfs"' bin/nix-xd-qualify-starwisp-shared
grep -Fq 'COREOS_GUEST_OCI_ARCHIVE="$archive"' bin/nix-xd-qualify-starwisp-shared
grep -Fq 'exec bash "$repo/bin/nix-xd-qualify-starwisp"' bin/nix-xd-qualify-starwisp-shared
if grep -Eq 'podman (cp|save|load)|volume rm|nix store gc|rm -rf /nix' bin/nix-xd-qualify-starwisp-shared; then
  echo 'Shared store preparer may not copy/migrate/delete the store' >&2; exit 1
fi
grep -Fq 'NIX_9P_NESTED_PODMAN_READONLY' bin/nix-xd-wisp-ssh
echo 'PASS: Starwisp fresh shared-store closure preparation and guest qualifier dispatch'
