#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/workspaces/compositions/demo"
git -C "$tmp/workspaces/compositions/demo" init -q
git -C "$tmp/workspaces/compositions/demo" config user.name Test
git -C "$tmp/workspaces/compositions/demo" config user.email test@example.invalid
printf 'test\n' >"$tmp/workspaces/compositions/demo/file.txt"
git -C "$tmp/workspaces/compositions/demo" add file.txt
git -C "$tmp/workspaces/compositions/demo" commit -qm initial

cat >"$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$NIX_XD_TEST_RECORD"
if [[ "$1" == cp && "${FAIL_COPY:-0}" == 1 ]]; then
  exit 31
fi
MOCK
chmod +x "$tmp/bin/podman"

export PATH="$tmp/bin:$PATH"
export NIX_XD_TEST_RECORD="$tmp/calls"
export NIX_XD_PROVIDER=podman NIX_XD_SCOPE=nix-xd-arm
export NIX_XD_WORKSPACES="$tmp/workspaces" NIX_XD_CHECKOUT=compositions/demo
export NIX_XD_SYSTEM=aarch64-linux
export TMPDIR="$tmp"

bash "$repo/bin/nix-xd-task" stage >"$tmp/success.log"
grep -Fq 'Staged compositions/demo at ' "$tmp/success.log"
grep -Fq 'cp ' "$tmp/calls"
grep -Fq 'exec --user 0' "$tmp/calls"
grep -Fq 'chown -R 1000:1000' "$tmp/calls"
if compgen -G "$tmp/tmp.*" >/dev/null; then
  echo 'Staging left a temporary directory behind' >&2
  exit 1
fi

if FAIL_COPY=1 bash "$repo/bin/nix-xd-task" stage >"$tmp/failure.log" 2>&1; then
  echo 'A failed copy was reported as success' >&2
  exit 1
fi
if compgen -G "$tmp/tmp.*" >/dev/null; then
  echo 'Failed staging left a temporary directory behind' >&2
  exit 1
fi

if NIX_XD_CHECKOUT=. bash "$repo/bin/nix-xd-task" stage >/dev/null 2>&1; then
  echo 'Unsafe root checkout was accepted' >&2
  exit 1
fi

echo 'PASS: staging cleanup, failure propagation, and checkout containment'
