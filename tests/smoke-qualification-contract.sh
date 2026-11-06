#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat >"$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
echo "Injected provider failure" >&2
exit 19
MOCK
chmod +x "$tmp/bin/podman"
if PATH="$tmp/bin:$PATH" bash "$repo/bin/nix-xd-qualify-smoke" >"$tmp/qualify" 2>&1; then
  echo 'Qualification incorrectly succeeded without a valid runtime' >&2
  exit 1
fi
grep -Fq 'QUALIFICATION_RESULT=FAIL' "$tmp/qualify"
grep -Fq 'gate=preflight' "$tmp/qualify"

if bash "$repo/bin/nix-xd-log" nix-xd-smoke-podman test-failure bash -ec 'exit 17' >"$tmp/wrapper" 2>&1; then
  echo 'Logger swallowed nonzero command exit code' >&2
  exit 1
else
  rc=$?
  [[ "$rc" -eq 17 ]] || { echo "Logger exit code was $rc, expected 17" >&2; exit 1; }
fi
log="$(sed -n 's/^Diagnostic log: //p' "$tmp/wrapper" | head -1)"
[[ -f "$log" ]]
grep -Fq '(exit 17)' "$log"
rm -f "$log"
echo 'PASS: qualification fails closed and logger embeds the exact exit code'
