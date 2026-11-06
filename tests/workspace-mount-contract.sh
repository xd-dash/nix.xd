#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/workspaces"
printf '%s\n' '{ "description": "test" }' >"$tmp/workspaces/flake.nix"

cat >"$tmp/bin/container" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == exec ]]
[[ "$2" == nix-xd-bind ]]
[[ "$3" == /bin/bash ]]
hash="$(shasum -a 256 "$NIX_XD_WORKSPACES/flake.nix")"
hash="${hash%% *}"
if [[ "${WRONG_MOUNT:-0}" == 1 ]]; then hash=unrelated; fi
echo "$hash  /workspaces/flake.nix"
MOCK
chmod +x "$tmp/bin/container"
export PATH="$tmp/bin:$PATH"
export NIX_XD_PROVIDER=container NIX_XD_SCOPE=nix-xd-bind
export NIX_XD_WORKSPACES="$tmp/workspaces" NIX_XD_WORKSPACE_MODE=bind

bash "$repo/bin/nix-xd-workspace-check" >"$tmp/ok"
grep -Fq 'PASS: live read-only workspace mount' "$tmp/ok"

if WRONG_MOUNT=1 bash "$repo/bin/nix-xd-workspace-check" >"$tmp/bad" 2>&1; then
  echo 'Mismatched mounted workspace was accepted' >&2
  exit 1
fi

if NIX_XD_WORKSPACE_MODE=staged bash "$repo/bin/nix-xd-workspace-check" >"$tmp/bad" 2>&1; then
  echo 'Legacy staged checkout was accepted as a mounted workspace' >&2
  exit 1
fi

echo 'PASS: read-only host/guest mount digest comparison rejects incorrect or legacy mode'
