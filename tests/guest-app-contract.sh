#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash -n bin/nix-xd-guest-app
grep -Fq 'state=${GUEST_STATE_ROOT:-$HOME/.local/state/nix-xd/coreos}' bin/nix-xd-guest-app || {
  echo 'Direct guest-app state root drifted from Make' >&2
  exit 1
}
if grep -Eiq 'fatline|probot|skymill|logma|agni' bin/nix-xd-guest-app; then
  echo 'Generic guest executor contains an application name' >&2
  exit 1
fi
make -s -n guest-app FLAKE=example20261112/local/example TARGET='#guest-script' GUEST_APP_REV="$(printf 'a%.0s' {1..40})" ARGS_JSON='["status"]' >/dev/null
if make -s -n fatline-services-status >/dev/null 2>&1; then
  echo 'Legacy application target remains enabled by default' >&2
  exit 1
fi
make -s -n fatline-services-status ENABLE_LEGACY_APPLICATION_CONTROLLERS=1 >/dev/null
if make -s -n fatline-probot-vm1-runtime-preflight >/dev/null 2>&1; then
  echo 'Retired Probot-specific target still exists' >&2
  exit 1
fi
if NIX_XD_PROVIDER=podman NIX_XD_SYSTEM=aarch64-linux NIX_XD_FLAKE=example20261112/local/example \
  NIX_XD_TARGET='#guest-script' NIX_XD_GUEST_APP_REV=not-a-commit \
  COREOS_SSH_KEY=/does/not/exist bash bin/nix-xd-guest-app >/dev/null 2>&1; then
  echo 'Guest transport accepted an unpinned app' >&2
  exit 1
fi
echo NIX_XD_GENERIC_GUEST_APP_CONTRACT=passed
