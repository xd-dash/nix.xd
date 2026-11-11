#!/usr/bin/env bash
set -Eeuo pipefail
scope=${1:?scope} flake=${2:?flake}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ && $flake == /workspaces/* && $flake != *..* ]]
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
unit="$HOME/.config/containers/systemd/$scope.container"
[[ -f $unit && $(systemctl --user show "$scope.service" -p LoadState --value) == loaded ]]
grep -Fxq "ContainerName=$scope" "$unit"
state="$HOME/.local/state/nix-xd/builder-config"
install -d -m 700 "$state"
exec 9>"$state/$scope.lock";flock -n -x 9
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
[[ $(podman inspect "$scope" --format '{{.HostConfig.Privileged}}') == false ]]
podman exec "$scope" mkdir -p /nix/home/nixuser/.local/state/nix-xd
tool=$(podman exec "$scope" nix build --no-write-lock-file --print-out-paths --out-link /nix/home/nixuser/.local/state/nix-xd/builder-policy "$flake#builderPolicy")
[[ $tool =~ ^/nix/store/[a-z0-9]{32}-nix-xd-builder-policy$ ]]
oci=$(podman inspect "$scope" --format '{{.OCIConfigPath}}')
[[ -f $oci && -r $oci ]]
profile_dir="$HOME/.config/nix-xd/seccomp"
install -d -m 700 "$profile_dir"
policy="$profile_dir/$scope-nix-chroot.json"
temporary=$(mktemp "$profile_dir/.policy.XXXXXX")
trap 'rm -f "$temporary"' EXIT
podman exec -i "$scope" "$tool/bin/nix-xd-builder-policy" render < "$oci" > "$temporary"
chmod 600 "$temporary"
changed=0
if [[ -f $policy ]] && cmp -s "$policy" "$temporary"; then :;else mv -f "$temporary" "$policy";changed=1;fi
dir="$unit.d";mkdir -p "$dir"
file="$dir/32-nix-chroot-seccomp.conf"
expected=$(printf '[Container]\nSeccompProfile=%s\n' "$policy")
if [[ -f $file ]]; then [[ $(cat "$file") == "$expected" ]] || { echo 'Seccomp declaration differs' >&2;exit 1; }
else printf '%s\n' "$expected" > "$file";chmod 600 "$file";changed=1;fi
stamp=$(sha256sum "$policy" | cut -d ' ' -f 1)
if [[ $changed == 1 || ! -f $state/$scope-seccomp.applied || $(cat "$state/$scope-seccomp.applied") != "$stamp" ]]; then
  echo "BUILDER_SYSCALL_PROFILE_RESTART owner=$scope allow=sethostname,setdomainname"
  systemctl --user daemon-reload
  systemctl --user restart "$scope.service"
fi
systemctl --user is-active --quiet "$scope.service"
[[ $(podman inspect "$scope" --format '{{.HostConfig.Privileged}}') == false ]]
podman exec "$scope" sh -ec '
  test "$(id -u)" -ne 0
  grep -Eq "^CapEff:[[:space:]]+0+$" /proc/self/status
  grep -Eq "^Seccomp:[[:space:]]+2$" /proc/self/status
'
podman exec "$scope" "$tool/bin/nix-xd-builder-policy" probe
printf '%s\n' "$stamp" > "$state/$scope-seccomp.applied"
echo BUILDER_SYSCALL_PROFILE_RESULT=passed seccomp=filtered privileged=false
