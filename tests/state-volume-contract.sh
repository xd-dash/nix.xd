#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for script in "$repo/bin/nix-xd-state-volume" "$repo/bin/nix-xd-log" "$repo/bin/nix-xd-task"; do
  bash -n "$script"
done
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/podman" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == machine && "$2" == inspect ]]; then
  printf 'running\n'
  exit 0
fi
[[ "$1" == --connection && "$2" == coreos-arm64 ]] || exit 10
shift 2
case "$1 $2" in
  'volume exists') [[ -e "$MOCK_VOLUME" ]] ;;
  'volume create')
    printf '%s\n' "$*" > "$MOCK_VOLUME"
    ;;
  'volume inspect')
    [[ -e "$MOCK_VOLUME" ]] || exit 1
    if [[ "$*" == *"--format"* ]]; then
      if [[ "$3" == nix-xd-state-secret-qualification ]]; then
        printf '%s\n' '{"io.nix-xd.state.version":"1","io.nix-xd.state.kind":"secret","io.nix-xd.state.name":"qualification"}'
      else
        printf '%s\n' '{"io.nix-xd.state.version":"1","io.nix-xd.state.kind":"control","io.nix-xd.state.name":"orchestrator"}'
      fi
    else
      printf '%s\n' '[{"Name":"nix-xd-state-control-orchestrator"}]'
    fi
    ;;
  'run --rm')
    [[ "$*" == *"dst=/state,ro"* ]] || exit 11
    printf 'fixture archive'
    ;;
  *) printf 'Unexpected Podman call: %s\n' "$*" >&2; exit 12 ;;
esac
MOCK
chmod +x "$tmp/podman"
export MOCK_VOLUME="$tmp/volume"
export PATH="$tmp:$PATH"
runner="$repo/bin/nix-xd-state-volume"
bash "$runner" plan control orchestrator | grep -q 'STATE_VOLUME_PLAN=absent'
bash "$runner" provision control orchestrator | grep -q 'STATE_VOLUME_PROVISION=passed'
bash "$runner" provision control orchestrator | grep -q 'STATE_VOLUME_PROVISION=passed'
bash "$runner" inspect control orchestrator | grep -q 'STATE_VOLUME_INSPECT=passed'
bash "$runner" plan control orchestrator | grep -q 'STATE_VOLUME_PLAN=existing'
archive="$tmp/export.tar"
bash "$runner" export control orchestrator "$archive" | grep -q 'STATE_VOLUME_EXPORT=passed'
[[ "$(cat "$archive")" == 'fixture archive' ]]
if bash "$runner" export control orchestrator "$archive" >/dev/null 2>&1; then
  echo 'Export must refuse to overwrite an existing destination' >&2
  exit 1
fi
if bash "$runner" plan vm orchestrator >/dev/null 2>&1; then
  echo 'Unlabeled or differently labeled volume must not be adopted' >&2
  exit 1
fi
if bash "$runner" provision control '../bad' >/dev/null 2>&1; then
  echo 'Invalid volume identity must fail closed' >&2
  exit 1
fi
export MOCK_VOLUME="$tmp/secret-volume"
bash "$runner" plan secret qualification | grep -q 'STATE_VOLUME_PLAN=absent'
bash "$runner" provision secret qualification | grep -q 'STATE_VOLUME_PROVISION=passed'
grep -Fq -- '--label io.nix-xd.state.kind=secret' "$MOCK_VOLUME"
bash "$runner" plan secret qualification | grep -q 'STATE_VOLUME_PLAN=existing'
if bash "$runner" plan application qualification >/dev/null 2>&1; then
  echo 'Secret volume must not be adopted as another kind' >&2
  exit 1
fi
printf 'STATE_VOLUME_STATIC_RESULT=passed\n'
