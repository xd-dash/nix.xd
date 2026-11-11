#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
scope=${1:?Builder scope} volume=${2:?Primary volume}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ && $volume =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || exit 2
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
before=$(podman inspect "$scope" --format '{{.Id}}')
image=$(podman inspect "$scope" --format '{{.Image}}')
label=$(podman inspect "$scope" --format '{{.ProcessLabel}}')
mounted=$(podman inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')
[[ $mounted == "$volume" ]]
type=$(cut -d : -f 3 <<< "$label")
level=$(cut -d : -f 4- <<< "$label")
[[ $type =~ ^[A-Za-z0-9_]+$ && $level =~ ^[A-Za-z0-9_:,]+$ ]] || {
  echo 'Running builder has no usable SELinux label; comparison cannot isolate it' >&2; exit 1;
}
policy="$HOME/.config/nix-xd/seccomp/$scope-nix-chroot.json"
test -r "$policy"
probe=/nix/var/nix/gcroots/nix-xd/bootstrap-profile/tools/bin/nix-xd-proc-probe
options=(run --rm --pull=never --network none --read-only --user 1000:1000
  --label io.nix-xd.managed=true --label io.nix-xd.role=bootstrap-probe
  --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable
  --security-opt 'unmask=/proc/*' --security-opt "seccomp=$policy"
  --mount "type=volume,src=$volume,dst=/nix,ro" --entrypoint "$probe")
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
baseline=0; disabled=0
printf 'BOOTSTRAP_PROFILE_COMPARISON_START owner=%s store=read-only\n' "$scope"
podman "${options[@]}" --security-opt "label=type:$type" --security-opt "label=level:$level" "$image" > "$tmp/baseline" 2>&1 || baseline=$?
cat "$tmp/baseline"
podman "${options[@]}" --security-opt label=disable "$image" > "$tmp/disabled" 2>&1 || disabled=$?
cat "$tmp/disabled"
[[ $(podman inspect "$scope" --format '{{.Id}}') == "$before" ]]
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
printf 'BOOTSTRAP_PROFILE_COMPARISON baseline=%s label_disabled=%s owner_unchanged=true store=read-only\n' "$baseline" "$disabled"
if [[ $baseline != 0 && $disabled == 0 ]] && grep -Fq 'mount /proc failed: Permission denied' "$tmp/baseline"; then
  echo BOOTSTRAP_PROFILE_COMPARISON_RESULT=isolated-selinux
else
  echo BOOTSTRAP_PROFILE_COMPARISON_RESULT=not-isolated
  exit 1
fi
