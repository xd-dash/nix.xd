#!/usr/bin/env bash
set -euo pipefail

source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/arm" "$tmp/bin" "$tmp/fakebin"
cp "$source_root/arm/bootstrap-podman.sh" "$tmp/arm/"
printf '{}\n' > "$tmp/flake.nix"
cat > "$tmp/bin/nix-xd-sync" <<'SYNC'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_LOG"
SYNC

cat > "$tmp/fakebin/uname" <<'MOCK'
#!/usr/bin/env bash
case "$1" in
  -s) echo Darwin ;;
  -m) echo arm64 ;;
  *) exit 2 ;;
esac
MOCK

cat > "$tmp/fakebin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf 'podman %s\n' "$*" >> "$MOCK_LOG"
case "$1 $2" in
  'machine inspect')
    if [[ "$*" == *'--format'* ]]; then printf 'running\n'; fi
    ;;
  'machine ssh')
    cat >> "$MOCK_SSH"
    ;;
  *) echo "Unexpected Podman command: $*" >&2; exit 11 ;;
esac
MOCK
chmod +x "$tmp/fakebin/"* "$tmp/bin/nix-xd-sync"
export PATH="$tmp/fakebin:$PATH"
export MOCK_LOG="$tmp/commands" MOCK_SSH="$tmp/ssh-script"
export NIX_XD_MACHINE=podman-machine-default
export NIX_XD_SCOPE=nix-xd-smoke-podman
export NIX_XD_WORKSPACES="$tmp"
export NIX_ALPINE_REV=ddb5f5e5d0cda8ebe82f2087664e320059ceb353
bash "$tmp/arm/bootstrap-podman.sh" >"$tmp/bootlog"

grep -Fq 'dash-xd/nix-alpine codex/nixxd-refresh-reset' "$tmp/commands"
grep -Fq "$NIX_ALPINE_REV" "$tmp/commands"
grep -Fq 'bash "$source/local/bootstrap.sh"' "$tmp/ssh-script"
grep -Fq 'export VOLUME="$scope-store"' "$tmp/ssh-script"
grep -Fq 'systemctl --user is-active --quiet "$scope.service"' "$tmp/ssh-script"

echo 'PASS: macOS Podman invokes pinned canonical Linux Quadlet bootstrap'
