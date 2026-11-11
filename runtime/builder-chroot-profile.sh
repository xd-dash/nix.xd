#!/usr/bin/env bash
set -Eeuo pipefail
scope=${1:?scope}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ ]] || exit 2
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
unit="$HOME/.config/containers/systemd/$scope.container"
[[ -f $unit && $(systemctl --user show "$scope.service" -p LoadState --value) == loaded ]]
grep -Fxq "ContainerName=$scope" "$unit"
install -d -m 700 "$HOME/.local/state/nix-xd/builder-config"
exec 9>"$HOME/.local/state/nix-xd/builder-config/$scope.lock";flock -n -x 9
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
[[ $(podman inspect "$scope" --format '{{.HostConfig.Privileged}}') == false ]]
dir="$unit.d";mkdir -p "$dir"
file="$dir/30-nix-chroot-profile.conf"
expected=$(printf '[Container]\nUnmask=/proc/*\n')
if [[ -e $file ]]; then [[ $(cat "$file") == "$expected" ]] || { echo 'Builder namespace profile differs' >&2;exit 1; }
else printf '%s\n' "$expected" > "$file";chmod 600 "$file";fi
proc_masks=$(podman exec "$scope" awk '$5 ~ "^/proc/" { print $5 }' /proc/self/mountinfo)
if grep -Eq '^/proc(/|$)' <<< "$proc_masks"; then
  echo "BUILDER_PROFILE_RESTART owner=$scope profile=nix-chroot unmask=/proc/*"
  systemctl --user daemon-reload
  systemctl --user restart "$scope.service"
fi
systemctl --user is-active --quiet "$scope.service"
[[ $(podman inspect "$scope" --format '{{.HostConfig.Privileged}}') == false ]]
proc_masks=$(podman exec "$scope" awk '$5 ~ "^/proc/" { print $5 }' /proc/self/mountinfo)
if grep -Eq '^/proc(/|$)' <<< "$proc_masks"; then echo 'Proc restrictions remain after profile apply' >&2;exit 1;fi
podman exec "$scope" sh -ec '
  test "$(id -u)" -ne 0
  grep -Eq "^CapEff:[[:space:]]+0+$" /proc/self/status
  grep -Eq "^Seccomp:[[:space:]]+2$" /proc/self/status
'
echo "BUILDER_PROFILE_RESULT=passed owner=$scope profile=nix-chroot seccomp=retained privileged=false"
