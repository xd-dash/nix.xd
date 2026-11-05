#!/usr/bin/env bash
set -euo pipefail
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/workspaces"
cp "$source_root/bin/nix-xd-plan" "$tmp/bin/nix-xd-plan"
cat >"$tmp/bin/nix-xd-sync" <<'SYNC'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$3/$4"
case "$1" in
  example/plan) mkdir -p "$3/$4/qualifications"; touch "$3/$4/qualifications/flake.nix"; echo '{"schemaVersion":2,"protocolVersion":1,"modules":[],"gates":{}}' >"$3/$4/qualifications/plan.json" ;;
  dash-xd/nix-alpine) mkdir -p "$3/$4/local" ;;
  *) exit 2 ;;
esac
SYNC
cat >"$tmp/bin/nix-xd-task" <<'TASK'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == stage ]]
printf '%s\n' "$NIX_XD_CHECKOUT" >>"$NIX_XD_STAGE_RECORD"
TASK
cat >"$tmp/bin/container" <<'CONTAINER'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$NIX_XD_TEST_RECORD"
CONTAINER
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" NIX_XD_TEST_RECORD="$tmp/exec" NIX_XD_STAGE_RECORD="$tmp/stages"
export PLAN_REPO=example/plan PLAN_BRANCH=main
export PLAN_REV=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export NIX_ALPINE_REV=037290d6713cb5efc548982c42b26f77f467e58a
export PLAN_CHECKOUT=compositions/plan PLAN_FILE=qualifications/plan.json
export PLAN_FLAKE=qualifications PLAN_TARGET=qualify-plan PLAN_GATE=all
export NIX_XD_PROVIDER=container NIX_XD_SCOPE=nix-xd-arm
export NIX_XD_WORKSPACES="$tmp/workspaces" PLAN_CAPABILITIES=nix-exec

bash "$tmp/bin/nix-xd-plan"
grep -Fx '/workspaces/compositions/plan/qualifications#qualify-plan' "$tmp/exec"
grep -Fx '/workspaces/compositions/plan/qualifications/plan.json' "$tmp/exec"
grep -Fx '/workspaces/nix-alpine/nix-alpine/local' "$tmp/exec"
grep -Fx 'compositions/plan' "$tmp/stages"
grep -Fx 'nix-alpine/nix-alpine' "$tmp/stages"
grep -Fx -- '--plan-checkout' "$tmp/exec"
grep -Fx -- '--gate' "$tmp/exec"

if PLAN_CAPABILITIES=host-systemd bash "$tmp/bin/nix-xd-plan" >"$tmp/reject" 2>&1; then
  echo "Host-systemd plan was accepted by Apple Container" >&2
  exit 1
fi
grep -Fq 'supports only PLAN_CAPABILITIES=nix-exec' "$tmp/reject"

if PLAN_CHECKOUT=. bash "$tmp/bin/nix-xd-plan" >"$tmp/reject" 2>&1; then
  echo "Root workspace checkout accepted" >&2
  exit 1
fi
grep -Fq 'Unsafe' "$tmp/reject"

printf '%s\n' 'Plan transport, capability fence, staging and traversal contracts passed.'
