#!/usr/bin/env bash
set -euo pipefail
scope=${1:?Qualification scope} image=${2:?Cached image} builder=${3:?Ordinary builder}
fail() { echo "TENANT_STORAGE_RESULT=failed reason=$*" >&2; exit 1; }
[[ $(getenforce) == Enforcing ]] || fail selinux-not-enforcing
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]] || fail rootful-runtime
podman image exists "$image" || fail missing-local-image
[[ $(podman inspect "$builder" --format '{{.State.Running}}') == true ]] || fail builder-not-running
runtime_dir=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
[[ -d $runtime_dir && $(stat -c %u "$runtime_dir") == "$(id -u)" ]] || fail runtime-directory
exec 9>"$runtime_dir/nix-xd-$scope.lock"
flock -n -x 9 || fail qualification-busy
a="$scope-a"; b="$scope-b"
pa=$(tenant_volume_name "$scope" a private); pb=$(tenant_volume_name "$scope" b private)
dac=$(tenant_volume_name "$scope" a dac); mac=$(tenant_volume_name "$scope" a mac)
shared=$(tenant_volume_name "$scope" shared artifacts)
for name in "$a" "$b"; do
  if podman container exists "$name"; then fail "existing-container:$name"; fi
done
for volume in "$pa" "$pb" "$dac" "$mac" "$shared"; do
  if podman volume exists "$volume"; then fail "existing-volume:$volume"; fi
done
temporary=$(mktemp -d)
containers=(); volumes=()
qualified=0
cleanup() {
  local rc=$? name item tenant store
  trap - EXIT
  for name in ${containers[@]+"${containers[@]}"}; do podman rm -f "$name" >/dev/null 2>&1 || rc=1; done
  for item in ${volumes[@]+"${volumes[@]}"}; do
    tenant=${item%%:*}; store=${item#*:}
    name=$(tenant_volume_name "$scope" "$tenant" "$store")
    if podman volume exists "$name"; then tenant_volume_remove "$scope" "$tenant" "$store" >/dev/null || rc=1; fi
  done
  rm -rf -- "$temporary"
  printf 'TENANT_STORAGE_CLEANUP exit=%s scope=%s\n' "$rc" "$scope"
  if [[ $rc == 0 && $qualified == 1 ]]; then
    echo TENANT_STORAGE_RESULT=passed uid_gid=distinct selinux=enforcing private_stores=protected
  else
    [[ $rc != 0 ]] || rc=1
    echo TENANT_STORAGE_RESULT=failed
  fi
  exit "$rc"
}
trap cleanup EXIT
podman unshare cat /proc/self/uid_map > "$temporary/available-uids"
podman unshare cat /proc/self/gid_map > "$temporary/available-gids"
for file in available-uids available-gids; do
  awk '$1 <= 32768 && $1+$3 >= 49152 {found=1} END {exit !found}' "$temporary/$file" || fail insufficient-subordinate-ids
done
for spec in a:private b:private a:dac a:mac shared:artifacts; do
  volumes+=("$spec")
  tenant_volume_create "$scope" "${spec%%:*}" "${spec#*:}" >/dev/null
done
common=(--pull=never --network none --read-only --cap-drop all --user 1000:1000)
podman run --rm --pull=never --network none --read-only --cap-drop all --user 0:0 \
  --label io.nix-xd.managed=true --label io.nix-xd.role=storage-probe --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable \
  -v "$shared:/share:z,nocreate" --entrypoint /bin/sh "$image" -ec \
  'chmod 0777 /share; printf shared-artifact > /share/canary; chmod 0644 /share/canary'
containers+=("$a")
podman run -d --name "$a" "${common[@]}" --uidmap 0:32768:8192 --gidmap 0:32768:8192 \
  --security-opt label=type:container_t \
  --label io.nix-xd.managed=true --label io.nix-xd.role=tenant-runtime --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable \
  -v "$pa:/private:Z,U,nocreate" -v "$dac:/dac:z,U,nocreate" -v "$mac:/mac:Z,U,nocreate" \
  -v "$shared:/share:ro,nocreate" --entrypoint /bin/sh "$image" -ec '
    umask 077; mkdir -p /private/store; chmod 0700 /private /private/store
    printf tenant-a > /private/store/canary
    printf dac-fixture > /dac/canary; chmod 0700 /dac
    printf mac-fixture > /mac/canary; chmod 0755 /mac; chmod 0644 /mac/canary
    exec sleep 600
  ' >/dev/null
containers+=("$b")
podman run -d --name "$b" "${common[@]}" --uidmap 0:40960:8192 --gidmap 0:40960:8192 \
  --security-opt label=type:container_t \
  --label io.nix-xd.managed=true --label io.nix-xd.role=tenant-runtime --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable \
  -v "$pb:/private:Z,U,nocreate" -v "$shared:/share:ro,nocreate" --entrypoint /bin/sh "$image" -ec '
    umask 077; mkdir -p /private/store; chmod 0700 /private /private/store
    printf tenant-b > /private/store/canary; exec sleep 600
  ' >/dev/null
# Readiness also verifies each tenant can initialize its own protected directory.
for name in "$a" "$b"; do
  ready=0
  for attempt in $(seq 1 30); do
    if podman exec "$name" sh -ec 'test -f /private/store/canary; test "$(id -u)" = 1000; grep -Eq "^CapEff:[[:space:]]+0+$" /proc/self/status'; then ready=1; break; fi
    sleep 0.2
  done
  [[ $ready == 1 ]] || fail "tenant-not-ready:$name"
done
for name in "$a" "$b" "$builder"; do
  pid=$(podman inspect "$name" --format '{{.State.Pid}}')
  [[ $pid =~ ^[0-9]+$ && $pid != 0 ]] || fail missing-pid
  printf 'TENANT_HOST_IDENTITY container=%s uid=%s gid=%s\n' "$name" \
    "$(awk '/^Uid:/{print $3}' "/proc/$pid/status")" "$(awk '/^Gid:/{print $3}' "/proc/$pid/status")"
  if [[ $name == "$builder" ]]; then
    builder_uid=$(awk '/^Uid:/{print $3}' "/proc/$pid/status")
    builder_gid=$(awk '/^Gid:/{print $3}' "/proc/$pid/status")
  else
    cat "/proc/$pid/uid_map" > "$temporary/$name.uids"
    cat "/proc/$pid/gid_map" > "$temporary/$name.gids"
    printf 'TENANT_UID_MAP container=%s\n' "$name"; cat "$temporary/$name.uids"
    printf 'TENANT_GID_MAP container=%s\n' "$name"; cat "$temporary/$name.gids"
  fi
done
for kind in uids gids; do
  awk 'FNR==NR {start[NR]=$2;end[NR]=$2+$3;count=NR;next} {for(i=1;i<=count;i++) if($2<end[i] && $2+$3>start[i]) exit 1}' \
    "$temporary/$a.$kind" "$temporary/$b.$kind" || fail overlapping-tenant-mappings
  identity=$builder_uid; [[ $kind != gids ]] || identity=$builder_gid
  for name in "$a" "$b"; do
    awk -v identity="$identity" 'identity >= $2 && identity < $2+$3 {exit 1}' "$temporary/$name.$kind" || fail builder-identity-in-tenant-range
  done
done
label_a=$(podman inspect "$a" --format '{{.ProcessLabel}}')
label_b=$(podman inspect "$b" --format '{{.ProcessLabel}}')
level_a=$(cut -d : -f 4- <<< "$label_a"); level_b=$(cut -d : -f 4- <<< "$label_b")
[[ $label_a == *:container_t:s0:* && $label_b == *:container_t:s0:* && $level_a != "$level_b" ]] || fail tenant-labels
printf 'TENANT_SELINUX a=%s b=%s\n' "$label_a" "$label_b"
probe() {
  local actor="$1" level="$2" volume="$3" path="$4" expected="$5"
  podman run --rm "${common[@]}" --userns="container:$actor" \
    --label io.nix-xd.managed=true --label io.nix-xd.role=storage-probe --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable \
    --security-opt label=type:container_t --security-opt "label=level:$level" -v "$volume:/probe:ro,nocreate" \
    --entrypoint /bin/sh "$image" -ec '
      if test "$2" = allow; then cat "$1" >/dev/null
      else if cat "$1" >/dev/null 2>&1; then exit 1; fi; fi
    ' -- "/probe/$path" "$expected"
}
# Identical mappings, different labels: isolate MAC. Different mappings,
# shared filesystem label: isolate DAC. No probe relabels another volume.
probe "$b" "$level_b" "$mac" canary deny
probe "$b" "$level_a" "$mac" canary allow
probe "$b" "$level_b" "$dac" canary deny
probe "$a" "$level_b" "$dac" canary allow
probe "$b" "$level_b" "$pa" store/canary deny
probe "$a" "$level_a" "$pb" store/canary deny
echo TENANT_STORAGE_BOUNDARIES=passed dac=true mac=true cross_tenant=denied
for name in "$a" "$b"; do
  podman exec "$name" sh -ec '
    test "$(cat /share/canary)" = shared-artifact
    if touch /share/forbidden 2>/dev/null; then exit 1; fi
    test ! -e /other-tenant
  '
done
echo TENANT_SHARED_GRANT=passed read_only=true
for volume in "$pa" "$pb"; do
  path=$(podman volume inspect "$volume" --format '{{.Mountpoint}}')
  if cat "$path/store/canary" >/dev/null 2>&1; then fail ordinary-host-user-read-private-store; fi
done
builder_label=$(podman inspect "$builder" --format '{{.ProcessLabel}}')
builder_type=$(cut -d : -f 3 <<< "$builder_label"); builder_level=$(cut -d : -f 4- <<< "$builder_label")
[[ $builder_type == container_userns_t || $builder_type == container_t ]] || fail builder-unconfined
builder_ns=$(podman exec "$builder" readlink /proc/self/ns/user)
podman_ns=$(podman unshare readlink /proc/self/ns/user)
builder_userns=$(tenant_probe_userns "$builder_ns" "$podman_ns" "$builder")
builder_user=$(podman exec "$builder" id -u); builder_group=$(podman exec "$builder" id -g)
[[ $builder_user == 1000 && $builder_group == 1000 ]] || fail unexpected-builder-user
printf 'TENANT_BUILDER_PROBE namespace=%s mode=%s uid=%s gid=%s\n' "$builder_ns" "$builder_userns" "$builder_user" "$builder_group"
podman run --rm "${common[@]}" --userns="$builder_userns" \
  --label io.nix-xd.managed=true --label io.nix-xd.role=storage-probe --label "io.nix-xd.scope=$scope" --label io.nix-xd.lifecycle=disposable \
  --security-opt "label=type:$builder_type" --security-opt "label=level:$builder_level" \
  -v "$pa:/probe:ro,nocreate" --entrypoint /bin/sh "$image" -ec \
  'test "$(readlink /proc/self/ns/user)" = "$1"
   test "$(id -u)" = "$2"; test "$(id -g)" = "$3"
   grep -Eq "^CapEff:[[:space:]]+0+$" /proc/self/status
   if cat /probe/store/canary >/dev/null 2>&1; then exit 1; fi' \
  -- "$builder_ns" "$builder_user" "$builder_group"
echo TENANT_HOST_BUILDER_READ=denied
if tenant_volume_remove "$scope" a private; then fail deleted-in-use-volume; fi
echo TENANT_DELETE_WHILE_ATTACHED=denied
before_b=$(podman inspect "$b" --format '{{.Id}}')
podman stop -t 5 "$a" >/dev/null; podman rm "$a" >/dev/null
containers=("$b")
tenant_volume_remove "$scope" a private >/dev/null
if podman volume exists "$pa"; then fail tenant-volume-not-deleted; fi
[[ $(podman inspect "$b" --format '{{.Id}}') == "$before_b" ]]
podman exec "$b" sh -ec 'test "$(cat /private/store/canary)" = tenant-b; test "$(cat /share/canary)" = shared-artifact'
echo TENANT_SCOPED_DELETE=passed peer=unchanged
qualified=1
