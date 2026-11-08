#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
bash -n qualifiers/dispatch.sh qualifiers/modules/secrets.sh bin/nix-xd-task
for arch in arm64 amd64; do
  case "$arch" in arm64) system=aarch64-linux ;; amd64) system=x86_64-linux ;; esac
  plan="$(make -sn plan ARCH="$arch")"
  [[ "$plan" == *"System=%s"* && "$plan" == *"'$system'"* ]] ||
    { printf 'Architecture selection missing from plan: %s\n' "$arch" >&2; exit 1; }
  task="$(make -sn show ARCH="$arch")"
  [[ "$task" == *"NIX_XD_SYSTEM='$system'"* ]] ||
    { printf 'Architecture selection missing from generic task: %s\n' "$arch" >&2; exit 1; }
  qual="$(make -sn qualify MODULES=secrets ARCH="$arch")"
  [[ "$qual" == *"NIX_XD_SYSTEM='$system'"* && "$qual" == *'qualifiers/dispatch.sh'* ]] ||
    { printf 'Architecture selection missing from qualifier: %s\n' "$arch" >&2; exit 1; }
done
if make -sn plan ARCH=bad >/dev/null 2>&1; then
  echo 'Unsupported architecture accepted' >&2
  exit 1
fi
normal="$(make -sn qualify ARCH=arm64)"
[[ "$normal" == *'bin/nix-xd-task "run"'* ]] ||
  { echo 'Legacy flake-owned qualifier behavior changed' >&2; exit 1; }
combined="$(make -sn qualify QUALIFY_APP=1 MODULES=secrets FLAKE=components/example ARCH=arm64)"
[[ "$combined" == *'bin/nix-xd-task "run"'* && "$combined" == *'qualifiers/dispatch.sh'* ]] ||
  { echo 'Application qualifier and optional modules did not compose' >&2; exit 1; }
if make --no-print-directory --silent qualify QUALIFY_APP=bad >/dev/null 2>&1; then
  echo 'Invalid application qualification switch accepted' >&2
  exit 1
fi
store="$(make -sn qualify MODULES=store-recreation ARCH=amd64 PROVIDER=podman)"
[[ "$store" == *"NIX_XD_SYSTEM='x86_64-linux'"* && "$store" == *'qualifiers/dispatch.sh'* ]] ||
  { echo 'Native store recreation module not dispatched through the common interface' >&2; exit 1; }
grep -Fq 'service restart "$scope.service"' qualifiers/modules/store-recreation.sh
grep -Fq 'podman machine ssh "$machine" systemctl --user "$@"' qualifiers/modules/store-recreation.sh
grep -Fq 'service() { systemctl --user "$@"; }' qualifiers/modules/store-recreation.sh
grep -Fq 'STORE_RECREATION_STORE_PRESERVED=passed' qualifiers/modules/store-recreation.sh
grep -Fq 'bin/nix-xd-store-export-check' qualifiers/modules/store-recreation.sh
if NIX_XD_QUALIFY_MODULES=unknown bash qualifiers/dispatch.sh >/dev/null 2>&1; then
  echo 'Unknown qualifier accepted' >&2
  exit 1
fi
if NIX_XD_QUALIFY_MODULES='../secrets' bash qualifiers/dispatch.sh >/dev/null 2>&1; then
  echo 'Unsafe qualifier path accepted' >&2
  exit 1
fi
grep -Fq 'mktemp -d /tmp/nix-xd-secrets.' qualifiers/modules/secrets.sh
grep -Fq 'SOPS_AGE_KEY_FILE="$key"' qualifiers/modules/secrets.sh
grep -Fq 'jq -cS . "$plaintext"' qualifiers/modules/secrets.sh
grep -Fq 'jq -cS . "$roundtrip"' qualifiers/modules/secrets.sh
grep -Fq 'cmp -s "$scratch/expected.canonical.json" "$scratch/actual.canonical.json"' qualifiers/modules/secrets.sh
grep -Fq 'trap cleanup EXIT' qualifiers/modules/secrets.sh
if grep -Eq '(nix (build|store add)|podman cp|/nix/store/.*keys.txt)' qualifiers/modules/secrets.sh; then
  echo 'Secrets qualifier must not store private material in Nix' >&2
  exit 1
fi
printf 'PASS: Modular qualifier dispatch, fail-closed runtime architecture and isolated age/SOPS gate\n'
