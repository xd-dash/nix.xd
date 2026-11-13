#!/usr/bin/env bash
set -Eeuo pipefail
scope=${1:?scope} name=${2:?name} volume=${3:?volume}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ && $name =~ ^[a-z][a-z0-9-]{0,39}$ && $volume =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || exit 2
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
path=/stores/$name
unit="$HOME/.config/containers/systemd/$scope.container"
[[ -f $unit && $(systemctl --user show "$scope.service" -p LoadState --value) == loaded ]]
grep -Fxq "ContainerName=$scope" "$unit"
install -d -m 700 "$HOME/.local/state/nix-xd/builder-config"
exec 9>"$HOME/.local/state/nix-xd/builder-config/$scope.lock";flock -n -x 9
[[ $(podman inspect "$scope" --format '{{.State.Running}}') == true ]]
# A volume already attached anywhere else must not gain a second writer.
for id in $(podman ps -aq); do
  mounts=$(podman inspect "$id" --format '{{range .Mounts}}{{printf "%s|%s\n" .Name .Destination}}{{end}}')
  while IFS='|' read -r mounted destination; do
    if [[ $mounted == "$volume" ]]; then
      [[ $(podman inspect "$id" --format '{{.Name}}') == "$scope" && $destination == "$path" ]] || {
        echo 'Selected chroot volume is already attached elsewhere' >&2;exit 1;
      }
    fi
    if [[ $(podman inspect "$id" --format '{{.Name}}') == "$scope" && $destination == "$path" ]]; then
      [[ $mounted == "$volume" ]] || { echo 'Chroot destination already uses another mount' >&2;exit 1; }
    fi
  done <<< "$mounts"
done
if ! podman volume exists "$volume"; then podman volume create "$volume" >/dev/null;fi
image=$(podman inspect "$scope" --format '{{.Image}}')
# Initialize only an empty volume, using container root in rootless Podman.
podman run --rm --network none --read-only --user 0:0 --cap-drop all --cap-add CHOWN --cap-add DAC_OVERRIDE \
  --mount "type=volume,src=$volume,dst=/target" --entrypoint /bin/sh "$image" -ec '
    if [ -e /target/.nix-xd-chroot-v1 ]; then
      test "$(stat -c %u:%g /target)" = 1000:1000;exit
    fi
    test -z "$(find /target -mindepth 1 -maxdepth 1 -print -quit)" || { echo "Refusing nonempty unmarked chroot volume" >&2;exit 1; }
    chown 1000:1000 /target
    touch /target/.nix-xd-chroot-v1
  '
dir="$unit.d";mkdir -p "$dir"
file="$dir/20-chroot-$name.conf"
expected=$(printf '[Container]\nVolume=%s:%s\n' "$volume" "$path")
if [[ -e $file ]]; then [[ $(cat "$file") == "$expected" ]] || { echo 'Chroot declaration differs' >&2;exit 1; }
else printf '%s\n' "$expected" > "$file";chmod 600 "$file";fi
actual=$(podman inspect "$scope" --format '{{range .Mounts}}{{println .Name .Destination .RW}}{{end}}')
if ! grep -Fxq "$volume $path true" <<< "$actual"; then
  echo "CHROOT_ATTACH_RESTART owner=$scope path=$path"
  systemctl --user daemon-reload
  systemctl --user restart "$scope.service"
fi
systemctl --user is-active --quiet "$scope.service"
actual=$(podman inspect "$scope" --format '{{range .Mounts}}{{println .Name .Destination .RW}}{{end}}')
grep -Fxq "$volume $path true" <<< "$actual"
podman exec "$scope" test -w "$path"
echo "CHROOT_ATTACH_RESULT=passed owner=$scope volume=$volume path=$path"
