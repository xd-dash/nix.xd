#!/usr/bin/env bash
set -Eeuo pipefail
scope=${1:?scope} flake=${2:-} selinux=${3:-keep}
[[ $selinux == keep || $selinux == disabled ]] || exit 2
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
if [[ $selinux == disabled ]]; then
  [[ $flake == /workspaces/* && $flake != *..* ]]
  label=$(podman inspect "$scope" --format '{{.ProcessLabel}}')
  selinux_file="$dir/31-nix-chroot-selinux.conf"
  selinux_expected=$(printf '[Container]\nSecurityLabelDisable=true\n')
  if [[ -e $selinux_file ]]; then [[ $(cat "$selinux_file") == "$selinux_expected" ]] || { echo 'SELinux declaration differs' >&2;exit 1; };fi
  if [[ -n $label ]]; then
    # Compare only the SELinux setting, with a read-only view of the same store.
    echo BUILDER_SELINUX_COMPARISON=starting store=read-only
    podman exec "$scope" mkdir -p /nix/home/nixuser/.local/state/nix-xd
    probe=$(podman exec "$scope" nix build --no-write-lock-file --print-out-paths --out-link /nix/home/nixuser/.local/state/nix-xd/proc-probe "$flake#namespaceProbe")
    [[ $probe =~ ^/nix/store/[a-z0-9]{32}-nix-xd-proc-probe$ ]]
    volume=$(podman inspect "$scope" --format '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}')
    [[ $volume =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]
    image=$(podman inspect "$scope" --format '{{.Image}}')
    type=$(cut -d : -f 3 <<< "$label")
    level=$(cut -d : -f 4- <<< "$label")
    [[ $type =~ ^[a-zA-Z0-9_]+$ && $level =~ ^[a-zA-Z0-9_:,]+$ ]]
    options=(run --rm --pull=never --network none --user 1000:1000 --security-opt 'unmask=/proc/*'
      --mount "type=volume,src=$volume,dst=/nix,ro" --entrypoint "$probe/bin/nix-xd-proc-probe")
    baseline=0;unlabelled=0
    podman "${options[@]}" --security-opt "label=type:$type" --security-opt "label=level:$level" "$image" || baseline=$?
    podman "${options[@]}" --security-opt label=disable "$image" || unlabelled=$?
    echo "BUILDER_SELINUX_COMPARISON baseline=$baseline label_disabled=$unlabelled"
    [[ $baseline -ne 0 && $unlabelled -eq 0 ]] || {
      echo 'SELinux comparison did not isolate the failure; owner unchanged' >&2;exit 1;
    }
    printf '%s\n' "$selinux_expected" > "$selinux_file";chmod 600 "$selinux_file"
    echo "BUILDER_PROFILE_RESTART owner=$scope selinux=disabled builder_only=true"
    systemctl --user daemon-reload
    systemctl --user restart "$scope.service"
    [[ -z $(podman inspect "$scope" --format '{{.ProcessLabel}}') ]]
  else
    [[ -f $selinux_file ]] || { echo 'Unlabelled owner has no managed declaration' >&2;exit 1; }
  fi
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
if [[ -n ${probe:-} ]]; then podman exec "$scope" "$probe/bin/nix-xd-proc-probe";fi
echo "BUILDER_PROFILE_RESULT=passed owner=$scope profile=nix-chroot seccomp=retained privileged=false"
