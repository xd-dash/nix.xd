#!/usr/bin/env bash
set -Eeuo pipefail
# The lifecycle fixture exercises the ordinary Wisp path, not the optional
# 9P/closure gates. Ignore caller overrides so check-static is hermetic.
unset COREOS_NIX_STORE_VOLUME COREOS_GUEST_PROBE_ROOTFS
unset COREOS_GUEST_NIX_EXECUTABLE COREOS_GUEST_DYNAMIC_EXECUTABLE
unset COREOS_GUEST_OCI_ARCHIVE COREOS_AGNI_REV
unset NIX_XD_QUALIFY_WORKLOAD NIX_XD_WORKLOAD
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/work/bin" "$tmp/work/.state/coreos/starwisp"
cp "$root/bin/nix-xd-qualify-starwisp" "$tmp/work/bin/"
git -C "$tmp/work" init -q
git -C "$tmp/work" -c user.name=test -c user.email=test@example.invalid add bin/nix-xd-qualify-starwisp
git -C "$tmp/work" -c user.name=test -c user.email=test@example.invalid commit -qm initial
export MOCK_ROOT="$tmp/work" MOCK_MODE=success
cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$*" in
  'machine inspect coreos-arm64 --format {{.State}}') echo running ;;
  'machine inspect coreos-arm64 --format '*)
    echo 'machine_cpus=6 machine_memory_mib=8192 machine_disk_gib=120'
    ;;
  '--connection coreos-arm64 image inspect localhost/agni-coreos-qemu-runner:44.20261023.3.1-aarch64 --format {{.Id}}')
    printf 'sha256:%064d\n' 0 ;;
  '--connection coreos-arm64 logs coreos-starwisp') echo "QEMU mock container log" ;;
  *) echo "Unexpected Podman call: $*" >&2; exit 2 ;;
esac
MOCK
cat > "$tmp/work/bin/nix-xd-coreos-podman" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
state="$COREOS_STATE_ROOT/starwisp"
case "$1" in
  preflight)
    [[ -f "$state/base.qcow2" && -f "$state/config.ign" ]] ;;
  reset-failed)
    [[ "$MOCK_MODE" != running ]] || exit 1
    mkdir "$state/previous"
    for f in overlay.qcow2 manifest.txt serial.log wisp.log known_hosts; do
      [[ ! -e "$state/$f" ]] || mv "$state/$f" "$state/previous/$f"
    done
    ;;
  boot)
    echo mock-overlay > "$state/overlay.qcow2"
    echo port=2222 > "$state/manifest.txt"
    echo mock-boot > "$state/serial.log"
    ;;
  stop) echo stopped > "$state/stopped" ;;
  *) exit 2 ;;
esac
MOCK
cat > "$tmp/work/bin/nix-xd-wisp-ssh" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$MOCK_MODE" == failure ]]; then exit 42; fi
if [[ "$MOCK_MODE" == workload ]]; then
  for variable in COREOS_GUEST_PROBE_ROOTFS COREOS_GUEST_NIX_EXECUTABLE COREOS_GUEST_DYNAMIC_EXECUTABLE COREOS_GUEST_OCI_ARCHIVE; do
    if printenv "$variable" >/dev/null; then echo "Legacy variable reached Wisp: $variable" >&2; exit 1; fi
  done
  [[ "$COREOS_NIX_STORE_VOLUME" == nix-xd-arm-store ]]
fi
echo 'PASS: Wisp mocked'  > "$COREOS_STATE_ROOT/starwisp/wisp.log"
MOCK
chmod +x "$tmp/bin/podman"
chmod 0644 "$tmp/work/bin/nix-xd-coreos-podman" "$tmp/work/bin/nix-xd-wisp-ssh"
state="$tmp/work/.state/coreos/starwisp"
echo image > "$state/base.qcow2"
echo ignition > "$state/config.ign"
runner="sha256:$(printf '%064d' 0)"
{
  printf 'runner=%s\n' "$runner"
  printf 'disk_sha256=%s\n' "$(shasum -a 256 "$state/base.qcow2" | awk '{print $1}')"
  printf 'ignition_sha256=%s\n' "$(shasum -a 256 "$state/config.ign" | awk '{print $1}')"
} > "$state/build.txt"
ssh-keygen -q -t ed25519 -N '' -f "$tmp/testkey"
export PATH="$tmp/bin:$PATH"
export NIX_XD_MACHINE=coreos-arm64 COREOS_PROFILE=starwisp COREOS_STATE_ROOT="$tmp/work/.state/coreos"
export COREOS_SSH_KEY="$tmp/testkey"
bash "$tmp/work/bin/nix-xd-qualify-starwisp" > "$tmp/success.log"
grep -Fq 'QUALIFY_STARWISP_RESULT status=passed' "$tmp/success.log"
[[ -f "$state/stopped" ]]
result="$(find "$state/qualifications" -name qualification.txt | head -1)"
grep -Fxq 'status=passed' "$result"
grep -q '^wisp_log_sha256=' "$result"
grep -q '^serial_log_sha256=' "$result"
[[ -s "${result%/*}/wisp.log" ]]
rm "$state/stopped"
MOCK_MODE=failure bash "$tmp/work/bin/nix-xd-qualify-starwisp" > "$tmp/failure.log" 2>&1 && {
  echo 'Failed guest unexpectedly qualified' >&2; exit 1
}
grep -Fq 'QUALIFY_STARWISP_RESULT status=failed' "$tmp/failure.log"
[[ -f "$state/stopped" && -f "$state/previous/wisp.log" ]]
[[ -f "$state/base.qcow2" && -f "$state/config.ign" ]]
echo 'PASS: Starwisp orchestration retains evidence, archives prior guest and stops on failure'

# The manifest path must ignore stale caller probe values and still execute its hook.
mv "$state/previous" "$state/previous-failed"
cat > "$tmp/work/bin/nix-xd-workload-qualify" <<'MOCK_WORKLOAD'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$NIX_XD_WORKLOAD" == starwisp-probe ]]
mkdir -p "$COREOS_STATE_ROOT/starwisp/workloads/starwisp-probe/generation"
echo manifest > "$COREOS_STATE_ROOT/starwisp/workloads/starwisp-probe/generation/manifest.json"
echo 'WORKLOAD_QUALIFY_RESULT=passed'
MOCK_WORKLOAD
MOCK_MODE=workload NIX_XD_QUALIFY_WORKLOAD=1 NIX_XD_WORKLOAD=starwisp-probe \
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store \
  COREOS_GUEST_PROBE_ROOTFS=/stale/rootfs COREOS_GUEST_NIX_EXECUTABLE=/stale/nix \
  COREOS_GUEST_DYNAMIC_EXECUTABLE=/stale/hello COREOS_GUEST_OCI_ARCHIVE=/stale/archive \
  bash "$tmp/work/bin/nix-xd-qualify-starwisp" > "$tmp/workload.log"
grep -Fq 'WORKLOAD_QUALIFY_RESULT=passed' "$tmp/workload.log"
grep -Fq 'QUALIFY_STARWISP_RESULT status=passed' "$tmp/workload.log"
[[ -f "$state/stopped" ]]
echo 'PASS: manifest workload qualification excludes inherited legacy probe inputs'
