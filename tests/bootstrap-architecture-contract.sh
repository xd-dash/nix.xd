#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
bash -n bin/nix-xd-bootstrap-amd64 arm/init-nix-store.sh qualifiers/modules/store-recreation.sh
for arch in arm64 amd64; do
  output="$(make --no-print-directory -sn bootstrap ARCH="$arch" OS=Darwin)"
  expected="$( [[ "$arch" == arm64 ]] && echo 'arm/bootstrap-macos.sh' || echo 'bin/nix-xd-bootstrap-amd64' )"
  [[ "$output" == *"$expected"* ]] || {
    echo "Incorrect bootstrap adapter for $arch" >&2
    exit 1
  }
  plan="$(make --no-print-directory -sn plan ARCH="$arch")"
  system="$( [[ "$arch" == arm64 ]] && echo aarch64-linux || echo x86_64-linux )"
  [[ "$plan" == *"'$system'"* ]] || {
    echo "Incorrect Nix system for $arch" >&2
    exit 1
  }
done
# Pinned upstream remains a flake source, but the runtime image and store
# initialization must not depend on absent local/ scripts in that pin.
grep -Fq 'url = "github:dash-xd/nix-alpine/80a2821b7571edd09507f9b4349e2f1ed3daf900";' flake.nix
grep -Fq 'podman build --platform linux/amd64' bin/nix-xd-bootstrap-amd64
grep -Fq 'NIX_XD_DIRECT_STORE_READY' arm/init-nix-store.sh
grep -Fq 'COREOS_NIX_STORE_VOLUME="$volume"' bin/nix-xd-bootstrap-amd64
grep -Fq 'systemctl --user start "$scope.service"' bin/nix-xd-bootstrap-amd64
grep -Fq 'X86_BOOTSTRAP_RESULT=passed' bin/nix-xd-bootstrap-amd64
grep -Fq 'STORE_RECREATION_CONTAINER_CHANGED=passed' qualifiers/modules/store-recreation.sh
grep -Fq 'STORE_RECREATION_STORE_PRESERVED=passed' qualifiers/modules/store-recreation.sh
grep -Fq 'STORE_RECREATION_RESULT=passed' qualifiers/modules/store-recreation.sh
if grep -Eq 'volume rm|rm -rf /nix|cp -a /nix' bin/nix-xd-bootstrap-amd64; then
  echo 'AMD64 bootstrap may not destroy/migrate a Nix store' >&2
  exit 1
fi
printf 'PASS: Portable direct-volume image, native x86 bootstrap and modular recreation contract\n'
