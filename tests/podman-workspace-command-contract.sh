#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/workspaces"
printf 'fixture\n' >"$tmp/workspaces/flake.nix"

cat >"$tmp/bin/uname" <<'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == -s ]]; then echo Darwin; else /usr/bin/uname "$@"; fi
MOCK
cat >"$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == --connection && "${2:-}" == podman-machine-default ]] || exit 31
shift 2
[[ "${1:-}" == exec && "${2:-}" == nix-xd-smoke-podman ]] || exit 32
shift 2
[[ "${1:-}" == /bin/bash && "${2:-}" == -ec ]] || exit 33
[[ "${3:-}" == *'sha256sum /workspaces/flake.nix'* ]] || exit 34
[[ "${4:-}" == bash && "${5:-}" == podman ]] || exit 35
hash="$(shasum -a 256 "$NIX_XD_WORKSPACES/flake.nix")"
echo "${hash%% *}  /workspaces/flake.nix"
MOCK
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH"
export NIX_XD_PROVIDER=podman NIX_XD_MACHINE=podman-machine-default
export NIX_XD_SCOPE=nix-xd-smoke-podman
export NIX_XD_WORKSPACES="$tmp/workspaces" NIX_XD_WORKSPACE_MODE=bind

make --no-print-directory -s -C "$root" workspace-check \
  PROVIDER=podman MACHINE=podman-machine-default SCOPE=nix-xd-smoke-podman \
  WORKSPACES="$tmp/workspaces" >"$tmp/out"
grep -Fq 'PASS: podman mounted workspace' "$tmp/out"
if grep -Fq 'option requires an argument' "$tmp/out"; then exit 1; fi

echo 'PASS: Make workspace-check forwards complete bash script and arguments over named Podman connection'
