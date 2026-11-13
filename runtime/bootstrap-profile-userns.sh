#!/usr/bin/env bash
set -euo pipefail
scope=${1:?Builder scope} volume=${2:?Primary volume}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ && $volume =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || exit 2
[[ $(getenforce) == Enforcing ]] || { echo 'SELinux must be enforcing' >&2; exit 1; }
if [[ -f /etc/redhat-release ]] && command -v rpm >/dev/null 2>&1; then rpm -q container-selinux; fi
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
before=$(podman inspect "$scope" --format '{{.Id}}')
image=$(podman inspect "$scope" --format '{{.Image}}')
mounted=$(podman inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')
[[ $mounted == "$volume" ]]
mountpoint=$(podman volume inspect "$volume" --format '{{.Mountpoint}}')
context=$(stat -c %C "$mountpoint")
level=$(cut -d : -f 4- <<< "$context")
[[ $level =~ ^s0(:c[0-9]+([,.]c?[0-9]+)*)?$ ]] || { echo 'Cannot identify store label level without relabeling' >&2; exit 1; }
policy="$HOME/.config/nix-xd/seccomp/$scope-nix-chroot.json"
test -r "$policy"
printf 'BOOTSTRAP_USERNS_POLICY_CHECK=starting type=container_userns_t enforcing=true store=read-only\n'
podman run --rm --pull=never --network none --read-only --user 1000:1000 -i \
  --label io.nix-xd.managed=true --label io.nix-xd.role=bootstrap-probe \
  --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable \
  --security-opt 'unmask=/proc/*' --security-opt "seccomp=$policy" \
  --security-opt label=type:container_userns_t --security-opt "label=level:$level" \
  --mount "type=volume,src=$volume,dst=/nix,ro" --entrypoint /bin/bash "$image" -se <<'PROBE'
context=$(cat /proc/self/attr/current)
[[ $context == *:container_userns_t:* ]]
grep -Eq '^CapEff:[[:space:]]+0+$' /proc/self/status
tools=/nix/var/nix/gcroots/nix-xd/bootstrap-profile/tools
"$tools/bin/nix-xd-proc-probe"
"$tools/bin/nix-xd-builder-policy" probe
PROBE
[[ $(podman inspect "$scope" --format '{{.Id}}') == "$before" ]]
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
echo BOOTSTRAP_USERNS_POLICY_CHECK=passed owner_unchanged=true labels=retained store=read-only
