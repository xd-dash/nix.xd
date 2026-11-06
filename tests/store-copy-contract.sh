#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/container" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$NIX_XD_TEST_RECORD"
if [[ "${FAIL_COPY:-0}" == 1 ]]; then exit 27; fi
MOCK
chmod +x "$tmp/bin/container"
export PATH="$tmp/bin:$PATH" NIX_XD_TEST_RECORD="$tmp/calls"
export NIX_XD_PROVIDER=container NIX_XD_SCOPE=nix-xd-smoke
export NIX_XD_STORE_PATH=/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-smoke-test

bash "$repo/bin/nix-xd-store-copy" store-export
bash "$repo/bin/nix-xd-store-copy" store-import
grep -Fq 'nix copy --to "file://$2"' "$tmp/calls" || {
  echo 'Missing binary cache publish call' >&2; exit 1;
}
grep -Fq 'nix copy --no-check-sigs --from "file://$2"' "$tmp/calls" || {
  echo 'Missing binary cache import call' >&2; exit 1;
}
if NIX_XD_STORE_PATH=/etc/passwd bash "$repo/bin/nix-xd-store-copy" store-export >/dev/null 2>&1; then
  echo 'Unsafe store path accepted' >&2; exit 1
fi
if FAIL_COPY=1 bash "$repo/bin/nix-xd-store-copy" store-export >/dev/null 2>&1; then
  echo 'Failed publish was reported as successful' >&2; exit 1
fi
grep -Fq '/exchange/nix-cache' "$tmp/calls"
echo 'PASS: file cache transfer commands, path validation, failure propagation'
