#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runner="$root/bin/nix-xd-smoke-source"
runtime="$root/bin/nix-xd-qualify-ghxd-runtime"
auth="$root/bin/nix-xd-qualify-ghxd-auth"
plain="$root/tests/ghxd-runtime-flakes/plain/flake.nix"

bash -n "$runner" "$runtime" "$auth" "$root/bin/nix-xd-ghxd-auth" "$root/bin/nix-xd-ghxd-token-check"
grep -Fq 'go run ./cmd/ghxd-minimal "$@"' "$runner"
grep -Fq 'exec nix develop "$toolbox" -c go run' "$runner"
grep -Fq 'bash /workspaces/bin/nix-xd-smoke-source ghxd-secrets probe' "$plain"
grep -Fq 'SMOKE_EXECUTION=SOURCE' "$runtime"
grep -Fq 'SMOKE_EXECUTION=SOURCE' "$auth"
! grep -Fq 'tools/nix-alpine.sh build' "$runtime"
! grep -Fq 'tools/nix-alpine.sh build' "$auth"
! grep -Fq '.smoke-ghxd-state/bin/smoke' "$runtime"
! grep -Fq '.smoke-ghxd-state/bin/smoke' "$auth"
echo 'PASS: GHXD qualification is source-driven; binary-specific legacy tests remain separate'
