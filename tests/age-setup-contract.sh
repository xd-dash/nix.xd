#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
grep -Fq 'NIX_XD_AGE_VOLUME="$AGE_VOLUME"' "$repo/Makefile" && {
  echo 'Unexpected literal source substitution' >&2; exit 1;
} || :
grep -Fq 'NIX_XD_AGE_VOLUME="$(AGE_VOLUME)"' "$repo/Makefile"
grep -Fq 'NIX_ALPINE_AGE_VOLUME="$age_volume"' "$repo/arm/bootstrap-podman.sh"
grep -Fq 'NIX_ALPINE_AGE_ACCESS="$age_access"' "$repo/arm/bootstrap-podman.sh"
grep -Fq 'AGE_VOLUME="$age_volume"' "$repo/bin/nix-xd-qualify-ghxd-auth"
! grep -Fq 'bin/nix-xd-age-setup' "$repo/Makefile"
! grep -Fq 'AGE_SOURCE=' "$repo/bin/nix-xd-qualify-ghxd-auth"
echo 'PASS: bootstrap-owned named age volume forwarded; no macOS age key setup'
