#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
provider="${NIX_XD_PROVIDER:-podman}"
machine="${NIX_XD_MACHINE:-coreos-arm64}"
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
system="${NIX_XD_SYSTEM:-aarch64-linux}"
[[ "$provider" == podman ]] || { echo 'GC retention qualifier requires Podman' >&2; exit 2; }
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || { echo 'Invalid scope' >&2; exit 2; }
[[ "$machine" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Invalid machine' >&2; exit 2; }
runtime=(podman)
if [[ "$(uname -s)" == Darwin ]]; then
  runtime+=(--connection "$machine")
fi
actual="$("${runtime[@]}" exec "$scope" uname -m)"
case "$system:$actual" in
  aarch64-linux:aarch64|aarch64-linux:arm64|x86_64-linux:x86_64) ;;
  *) echo 'Runtime architecture mismatch' >&2; exit 1 ;;
esac
volume="$("${runtime[@]}" inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')"
[[ "$volume" == "$scope-store" ]] || { echo 'Unexpected owner store volume' >&2; exit 1; }
"${runtime[@]}" exec "$scope" sh -ec 'test "$(id -u)" = 1000; test -f /nix/.nix-xd-direct-volume-v2'
printf 'STORE_GC_RETENTION_RUNTIME=podman scope=%s system=%s\n' "$scope" "$system"
# Every Nix operation in the fixture explicitly selects its disposable store.
"${runtime[@]}" exec -i "$scope" bash -se < "$repo/tests/store-roots-gc.sh"
