#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat >"$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$NIX_XD_TEST_RECORD"
MOCK
chmod +x "$tmp/bin/podman"
export NIX_XD_TEST_RECORD="$tmp/command"
export PATH="$tmp/bin:$PATH"
cd "$repo"

make --no-print-directory --silent show PROVIDER=podman FLAKE=compositions/agni TARGET='#my-output'
grep -Fx -- 'flake' "$tmp/command"
grep -Fx -- 'show' "$tmp/command"
grep -Fx -- '/workspaces/compositions/agni#my-output' "$tmp/command"

make --no-print-directory --silent build PROVIDER=podman FLAKE=compositions/agni TARGET='#image'
grep -Fx -- 'build' "$tmp/command"
grep -Fx -- '--no-link' "$tmp/command"
grep -Fx -- '/workspaces/compositions/agni#image' "$tmp/command"

make --no-print-directory --silent qualify-process PROVIDER=podman FLAKE=compositions/agni
grep -Fx -- '/workspaces/compositions/agni#qualify-process' "$tmp/command"

make --no-print-directory --silent exec PROVIDER=podman CMD='nix --version'
grep -Fx -- 'bash' "$tmp/command"
grep -Fx -- 'nix --version' "$tmp/command"

printf '%s\n' 'Generic Make -> Nix command contract passed.'
