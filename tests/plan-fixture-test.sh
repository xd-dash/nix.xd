#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/compositions/protocol"
cp "$repo/tests/plan-fixture/plan.json" "$tmp/compositions/protocol/plan.json"

run_fixture() {
  python3 "$repo/tests/plan-fixture/runner.py" \
    --plan "$tmp/compositions/protocol/plan.json" \
    --gate "$1" \
    --workspaces "$tmp" \
    --toolbox test-runner \
    --nix-alpine-local "$tmp/nix-alpine/local" \
    --scope test \
    --plan-checkout compositions/protocol
}

run_fixture all >"$tmp/success"
run_fixture failure >"$tmp/failure" || [[ $? == 1 ]]

python3 - "$tmp/success" "$tmp/failure" <<'PY'
import json
import sys

def load(path):
    with open(path, encoding="utf-8") as f:
        prefix, value = f.read().strip().split("=", 1)
    assert prefix == "PLAN_EVIDENCE"
    return json.loads(value)

success = load(sys.argv[1])
assert success["status"] == "passed", success
assert success["order"] == ["bootstrap", "dependency", "parallel", "final"]
prepare = [e["module"] for e in success["events"] if e.get("phase") == "prepare"]
cleanup = [e["module"] for e in success["events"] if e.get("phase") == "cleanup"]
assert prepare == success["order"]
assert cleanup == list(reversed(prepare))
assert sum(e.get("module") == "bootstrap" and e.get("phase") == "execute"
           for e in success["events"]) == 1
failure = load(sys.argv[2])
assert failure["status"] == "failed"
assert failure["error"] == "injected failure: broken"
assert [e["module"] for e in failure["events"] if e.get("phase") == "cleanup"] == [
    "broken", "dependency", "bootstrap"
]
print("PASS: protocol graph, once-only dependency, fail-closed and reverse cleanup")
PY
