#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/uname" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == -s ]] && echo Darwin || /usr/bin/uname "$@"
MOCK
cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_LOG"
MOCK
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH"
export MOCK_LOG="$tmp/log"
export NIX_XD_PROVIDER=podman NIX_XD_MACHINE=podman-machine-default
export NIX_XD_SCOPE=nix-xd-smoke-podman
export NIX_XD_SYSTEM=aarch64-linux NIX_XD_WORKSPACE_MODE=bind
export NIX_XD_FLAKE=tests/plan-fixture NIX_XD_TARGET=
bash "$root/bin/nix-xd-task" show

grep -Fq -- '--connection podman-machine-default exec nix-xd-smoke-podman' "$tmp/log"
grep -Fq 'flake show --no-write-lock-file /workspaces/tests/plan-fixture' "$tmp/log"
if grep -Fq -- '--connection unrelated-machine' "$tmp/log"; then
  echo 'Podman task used unrelated machine' >&2
  exit 1
fi
echo 'PASS: Nix app commands execute through selected macOS Podman Machine'
