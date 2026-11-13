#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
if [[ "$*" == *' uname -m' ]]; then echo aarch64;exit 0;fi
printf '<%s>\n' "$@" > "$PROJECT_TEST_RECORD"
MOCK
chmod +x "$tmp/bin/podman"
export PROJECT_TEST_RECORD="$tmp/argv"
PATH="$tmp/bin:$PATH" NIX_XD_LOG_DIR="$tmp/logs" make -s -C "$repo" \
  ARCH=arm64 PROVIDER=podman MACHINE=selected SCOPE=fixture \
  PROJECT_RUNTIME_FLAKE=/workspaces/runtime PROJECT_FLAKE=/workspaces/project \
  PROJECT_APP=startup 'PROJECT_ARGS_JSON=["space value","quote value","--flag"]' project-run
for expected in '<exec>' '<fixture>' '</workspaces/runtime#project-launch>' '<--flake>' '</workspaces/project>' '<startup>' '<aarch64-linux>' '<["space value","quote value","--flag"]>'; do
  grep -Fxq -- "$expected" "$PROJECT_TEST_RECORD"
done
[[ $(find "$tmp/logs" -name 'fixture-project-run-*.log' | wc -l) -eq 1 ]]
echo 'PASS: Make launches the selected project through Nix-Alpine and the shared logger'

cat > "$tmp/local.mk" <<'CONFIG'
ARCH = arm64
PROVIDER = podman
MACHINE = selected
SCOPE = fixture
WORKLOAD_FLAKE = /workspaces/runtime
PROJECT_FLAKE = /workspaces/project
PROJECT_APP = startup
CONFIG
PATH="$tmp/bin:$PATH" NIX_XD_LOG_DIR="$tmp/config-logs" make -s -C "$repo" \
  NIX_XD_CONFIG="$tmp/local.mk" project-run
grep -Fxq '</workspaces/runtime#project-launch>' "$PROJECT_TEST_RECORD"
echo 'PASS: plain Make uses the selected generic local runtime configuration'
