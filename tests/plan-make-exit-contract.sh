#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/workspaces"

cat > "$tmp/bin/container" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == exec && "${3:-}" == nix ]]; then
  printf '%s\n' 'PLAN_EVIDENCE={"status":"failed","error":"injected failure"}'
  exit 17
fi
exit 0
MOCK
cat > "$tmp/bin/git" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
exit 0
MOCK
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" NIX_XD_LOG_DIR="$tmp/logs"

# With missing mandatory input, the actual Make target must fail before
# attempting any provider execution, and the logger must preserve the exit.
set +e
make --no-print-directory -s -C "$repo" qualify-plan \
  PROVIDER=container SCOPE=nix-xd-arm \
  PLAN_REPO=example/fixture PLAN_CHECKOUT=compositions/fixture \
  PLAN_FILE=tests/plan-fixture/plan.json PLAN_FLAKE=tests/plan-fixture \
  PLAN_CAPABILITIES=nix-exec WORKSPACES="$tmp/workspaces" \
  >"$tmp/output" 2>&1
status=$?
set -e
[[ "$status" -ne 0 ]] || { echo "Missing revision incorrectly passed" >&2; exit 1; }
grep -Fq '(exit ' "$tmp/output" || {
  echo "Make did not invoke the logged plan runner" >&2
  cat "$tmp/output" >&2
  exit 1
}
grep -Fq 'Result: ' "$tmp/output" || {
  echo "Missing diagnostic log result" >&2
  exit 1
}
printf 'PASS: Make qualify-plan preserves nonzero exit status and produces diagnostic log\n'
