#!/usr/bin/env bash
set -euo pipefail
provider="${NIX_XD_PROVIDER:-podman}"
base="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$provider" in
  podman) exec bash "$base/bootstrap-podman.sh" "$@" ;;
  container) exec bash "$base/bootstrap-container.sh" "$@" ;;
  *) echo "Unsupported provider: $provider (expected podman or container)" >&2; exit 2 ;;
esac
