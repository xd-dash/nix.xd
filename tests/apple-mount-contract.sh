#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
printf '%s\n' '{}' >"$tmp/flake.nix"
cat >"$tmp/bin/uname" <<'MOCK'
#!/usr/bin/env bash
case "${1:-}" in -s) echo Darwin ;; -m) echo arm64 ;; *) /usr/bin/uname "$@" ;; esac
MOCK
cat >"$tmp/bin/sw_vers" <<'MOCK'
#!/usr/bin/env bash
echo 26.1
MOCK
cat >"$tmp/bin/container" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$NIX_XD_MOCK_CALLS"
case "${1:-} ${2:-}" in
  "inspect "*|"volume inspect") exit 1 ;;
esac
if [[ "$*" == *"uname -m"* ]]; then printf 'aarch64\n'; fi
MOCK
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" NIX_XD_MOCK_CALLS="$tmp/commands"
export NIX_XD_SCOPE=nix-xd-bind NIX_XD_IMAGE=localhost/nix-xd:arm64
export NIX_XD_WORKSPACES="$tmp" NIX_XD_WORKSPACE_MODE=bind

bash "$repo/arm/bootstrap-container.sh" >"$tmp/bootstrap-log"
grep -F -- "--mount type=bind,source=$tmp,target=/workspaces,readonly" "$tmp/commands"
grep -F -- "--volume nix-xd-bind-store:/nix" "$tmp/commands"
grep -Fq 'workspace mode: bind' "$tmp/bootstrap-log"

# Staged is an explicit compatibility mode, never implicit fallback.
: >"$tmp/commands"
NIX_XD_WORKSPACE_MODE=staged NIX_XD_SCOPE=nix-xd-legacy \
  bash "$repo/arm/bootstrap-container.sh" >"$tmp/staged-log"
if grep -Fq 'target=/workspaces' "$tmp/commands"; then
  echo 'Explicit staged mode unexpectedly mounted host files' >&2
  exit 1
fi

mkdir -p "$tmp/smoke" "$tmp/exchange/nix-cache"
printf 'module github.com/xd-dash/smoke\n' > "$tmp/smoke/go.mod"
printf 'exchange-marker\n' > "$tmp/exchange/.nix-xd-exchange"

: >"$tmp/commands"
NIX_XD_SCOPE=nix-xd-smoke \
NIX_XD_SMOKE_SOURCE="$tmp/smoke" NIX_XD_EXCHANGE_ROOT="$tmp/exchange" \
  bash "$repo/arm/bootstrap-container.sh" >"$tmp/smoke-log"
grep -Fq -- "--mount type=bind,source=$tmp/smoke,target=/smoke" "$tmp/commands"
grep -Fq -- "--mount type=bind,source=$tmp/exchange,target=/exchange" "$tmp/commands"
grep -Fq -- "--volume nix-xd-smoke-store:/nix" "$tmp/commands"

: >"$tmp/commands"
NIX_XD_SCOPE=nix-xd-smoke-consumer NIX_XD_SMOKE_ACCESS=readonly NIX_XD_EXCHANGE_ACCESS=readonly \
NIX_XD_SMOKE_SOURCE="$tmp/smoke" NIX_XD_EXCHANGE_ROOT="$tmp/exchange" \
  bash "$repo/arm/bootstrap-container.sh" >"$tmp/consumer-log"
grep -Fq -- "--mount type=bind,source=$tmp/smoke,target=/smoke,readonly" "$tmp/commands"
grep -Fq -- "--mount type=bind,source=$tmp/exchange,target=/exchange,readonly" "$tmp/commands"
grep -Fq -- "--volume nix-xd-smoke-consumer-store:/nix" "$tmp/commands"
if grep -Fq -- "--volume nix-xd-smoke-store:/nix" "$tmp/commands"; then
  echo 'Consumer reused the producer Nix store' >&2
  exit 1
fi

echo 'PASS: new Apple runner mounts read-only host workspaces and persistent store'
