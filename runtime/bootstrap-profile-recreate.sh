#!/usr/bin/env bash
set -euo pipefail
scope=${1:?Builder scope}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ ]] || exit 2
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
unit="$HOME/.config/containers/systemd/$scope.container"
test -f "$unit"
grep -Fxq "ContainerName=$scope" "$unit"
grep -Fxq 'Label=io.nix-xd.managed=true' "$unit"
grep -Fxq 'Label=io.nix-xd.role=builder' "$unit"
[[ ! -d $unit.d ]] || { echo 'Legacy drop-ins exist; not a first-start profile' >&2; exit 1; }
printf 'BOOTSTRAP_PROFILE_RECREATE=stopping scope=%s stores=retained\n' "$scope"
systemctl --user stop "$scope.service"
if podman container exists "$scope"; then
  [[ $(podman inspect "$scope" --format '{{.State.Running}}') == false ]]
  podman rm "$scope"
fi
rm -- "$unit"
systemctl --user daemon-reload
printf 'BOOTSTRAP_PROFILE_RECREATE=removed scope=%s stores=retained\n' "$scope"
