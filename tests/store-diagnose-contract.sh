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
grep -Fq 'store-diagnose) runtime_cmd exec -i "$scope" sh -s <' bin/nix-xd-task
grep -Fq 'STORE_DIAG_RESULT=passed' bin/nix-xd-store-diagnose
grep -Fq 'nix path-info --all' bin/nix-xd-store-diagnose
grep -Fq 'find /nix/var/nix/gcroots -type l -print' bin/nix-xd-store-diagnose
if grep -Fq 'nix-store --gc' bin/nix-xd-store-diagnose; then
  echo 'Read-only inventory must not invoke Nix GC routines' >&2; exit 1
fi
if grep -Eq 'nix (build|store gc|store delete)|podman (cp|load|save)|rm -rf /nix' bin/nix-xd-store-diagnose; then
  echo 'Inventory diagnostics may not mutate the store' >&2
  exit 1
fi
# Reproduce Podman's closed-stdin behavior: without exec -i this fake
# provider returns success but no diagnostics, just like the observed empty log.
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cat > "$scratch/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --connection ]]; then shift 2; fi
[[ "${1:-}" == exec ]] || exit 97
shift
case "${1:-}" in
  -i)
    shift
    [[ "${1:-}" == nix-xd-arm && "${2:-}" == sh && "${3:-}" == -s ]] || exit 98
    grep -q "STORE_DIAG_FORMAT=v1" || exit 99
    printf 'STORE_DIAG_FORMAT=v1\\nSTORE_DIAG_RESULT=passed\\n'
    ;;
  nix-xd-arm)
    [[ "${2:-}" == uname && "${3:-}" == -m ]] || exit 98
    echo aarch64
    ;;
  *) exit 98 ;;
esac
MOCK
chmod +x "$scratch/podman"
report="$(PATH="$scratch:$PATH" NIX_XD_PROVIDER=podman NIX_XD_MACHINE=coreos-arm64 NIX_XD_SYSTEM=aarch64-linux NIX_XD_SCOPE=nix-xd-arm bash bin/nix-xd-task store-diagnose)"
[[ "$report" == *'STORE_DIAG_FORMAT=v1'* && "$report" == *'STORE_DIAG_RESULT=passed'* ]] ||
  { echo 'Store diagnostic transport unexpectedly returned an empty successful report' >&2; exit 1; }
echo 'PASS: Read-only shared Nix store inventory is logged through common runtime adapter'
