#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/uname" <<'MOCK'
#!/usr/bin/env bash
if [[ "$1" == -s ]]; then echo Darwin; else echo arm64; fi
MOCK
cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MOCK_CALLS"
case "$1 $2" in
  'machine inspect')
    [[ -f "$MOCK_EXISTS" ]] || exit 125
    if [[ "${3:-}" == '--format' ]]; then
      echo "${MOCK_CPUS:-6} ${MOCK_MEMORY:-8192} ${MOCK_DISK:-120} false"
    fi
    ;;
  'machine init') touch "$MOCK_EXISTS" ;;
  'system connection') [[ "$3" == default ]] ;;
  *) echo "Unexpected mock Podman action: $*" >&2; exit 2 ;;
esac
MOCK
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" MOCK_CALLS="$tmp/calls" MOCK_EXISTS="$tmp/existing"
: > "$MOCK_CALLS"
NIX_XD_MACHINE=starwisp-arm NIX_XD_MACHINE_MEMORY_MIB=8192   bash "$root/bin/nix-xd-machine" init >/dev/null
grep -Fq 'machine init --provider applehv --cpus 6 --memory 8192 --disk-size 120 --rootful=false starwisp-arm' "$MOCK_CALLS"
: > "$MOCK_CALLS"
NIX_XD_MACHINE=starwisp-arm NIX_XD_MACHINE_MEMORY_MIB=8192 NIX_XD_MACHINE_VERIFY=1   bash "$root/bin/nix-xd-machine" init >/dev/null
! grep -Fq 'machine init' "$MOCK_CALLS"
! grep -Fq 'system connection default' "$MOCK_CALLS"
if MOCK_MEMORY=2048 NIX_XD_MACHINE=starwisp-arm NIX_XD_MACHINE_VERIFY=1     bash "$root/bin/nix-xd-machine" check >/dev/null 2>&1; then
  echo "Undersized machine incorrectly passed verification" >&2; exit 1
fi
if NIX_XD_MACHINE=bad/name bash "$root/bin/nix-xd-machine" init >/dev/null 2>&1; then
  echo "Invalid machine name accepted" >&2; exit 1
fi
NIX_XD_MACHINE=starwisp-arm NIX_XD_MACHINE_DEFAULT=1   bash "$root/bin/nix-xd-machine" init >/dev/null
grep -Fq 'system connection default starwisp-arm' "$MOCK_CALLS"
echo 'PASS: Machine provisioned once, undersized machine rejected, connection default opt-in'
