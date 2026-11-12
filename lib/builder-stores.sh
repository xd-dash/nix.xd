#!/usr/bin/env bash
# Shared bootstrap policy; requires only Bash, including macOS Bash 3.2.
builder_stores_init() {
  local scope="$1" spec app volume seen=' '
  [[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || { echo "Invalid builder scope" >&2; return 1; }
  builder_store_volume="${NIX_XD_STORE_VOLUME:-$scope-store}"
  [[ "$builder_store_volume" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Invalid writable store volume' >&2; return 1; }
  [[ "${NIX_XD_PEER_STORES:-}" != *$'\n'* ]] || { echo 'Peer stores must be a single whitespace-separated list' >&2; return 1; }
  builder_peer_apps=(); builder_peer_volumes=(); builder_peer_count=0
  local specs=()
  read -r -a specs <<< "${NIX_XD_PEER_STORES:-}"
  for spec in ${specs[@]+"${specs[@]}"}; do
    app="${spec%%=*}"
    if [[ "$spec" == *=* ]]; then volume="${spec#*=}"; else volume="nix-xd-$app-store"; fi
    [[ "$app" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || { echo 'Invalid peer application name' >&2; return 1; }
    [[ "$volume" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Invalid peer store volume' >&2; return 1; }
    [[ "$volume" != "$builder_store_volume" ]] || { echo 'Own writable store cannot also be a peer' >&2; return 1; }
    [[ "$seen" != *" $app "* ]] || { echo 'Duplicate peer mount destination' >&2; return 1; }
    seen="$seen$app "
    builder_peer_apps+=("$app"); builder_peer_volumes+=("$volume"); builder_peer_count=$((builder_peer_count+1))
  done
}
builder_stores_check() {
  local volume i
  for ((i=0;i<builder_peer_count;i++)); do
    volume="${builder_peer_volumes[i]}"
    "$@" volume exists "$volume" || { echo "Selected peer store is missing: $volume" >&2; return 1; }
  done
}
builder_store_mounts() {
  local i
  printf 'Volume=%s:/nix\n' "$builder_store_volume"
  for ((i=0;i<builder_peer_count;i++)); do
    printf 'Volume=%s:/peer/%s:ro\n' "${builder_peer_volumes[i]}" "${builder_peer_apps[i]}"
  done
}
builder_store_assert_owner() {
  local scope="$1" volume="$2" destination="$3"
  shift 3
  local ids id mounts mounted writable owner
  [[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ && "$volume" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || return 2
  ids=$("$@" ps -aq) || return
  for id in $ids; do
    mounts=$("$@" inspect "$id" --format '{{range .Mounts}}{{if eq .Name "'"$volume"'"}}{{println .Destination .RW}}{{end}}{{end}}') || return
    while read -r mounted writable; do
      [[ "$writable" == true ]] || continue
      owner=$("$@" inspect "$id" --format '{{.Name}}') || return
      [[ "${owner#/}" == "$scope" && "$mounted" == "$destination" ]] || {
        echo "Writable store already attached: volume=$volume owner=$owner path=$mounted" >&2
        return 1
      }
    done <<< "$mounts"
  done
}
builder_quadlet() {
  local scope="$1" image="$2" description="$3" volume i
  [[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ && "$image" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]] || return 1
  printf '[Unit]\nDescription=%s\n\n[Container]\nImage=%s\nContainerName=%s\nPull=never\n' "$description" "$image" "$scope"
  local lifecycle="${NIX_XD_LIFECYCLE:-reusable}" composition="${NIX_XD_COMPOSITION_ID:-infrastructure}" placement="${NIX_XD_PLACEMENT_ID:-host}"
  [[ "$lifecycle" == reusable || "$lifecycle" == disposable ]] || return 2
  [[ "$composition" =~ ^[a-z][a-z0-9-]{0,39}$ && "$placement" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || return 2
  printf 'Label=io.nix-xd.managed=true\nLabel=io.nix-xd.schema=1\nLabel=io.nix-xd.role=builder\n'
  printf 'Label=io.nix-xd.scope=%s\nLabel=io.nix-xd.lifecycle=%s\nLabel=io.nix-xd.composition=%s\nLabel=io.nix-xd.placement=%s\n' "$scope" "$lifecycle" "$composition" "$placement"
  builder_store_mounts
  # Optional runtime data volumes; never place credentials inside the Nix store.
  local mount_spec mount_source mount_target mount_mode mount_extra
  local -a data_mounts=()
  read -r -a data_mounts <<< "${NIX_XD_DATA_MOUNTS:-}"
  for mount_spec in ${data_mounts[@]+"${data_mounts[@]}"}; do
    IFS=: read -r mount_source mount_target mount_mode mount_extra <<< "$mount_spec"
    [[ -z "$mount_extra" && "$mount_source" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || return 2
    [[ "$mount_target" =~ ^/run/nix-xd/mounts/[a-z][a-z0-9-]{0,39}$ ]] || return 2
    [[ "$mount_mode" == ro || "$mount_mode" == rw ]] || return 2
    [[ "$mount_source" != "$builder_store_volume" ]] || return 2
    printf 'Volume=%s:%s:%s\n' "$mount_source" "$mount_target" "$mount_mode"
  done
  if [[ -n ${NIX_XD_INITIAL_CHROOT_STORES:-} ]]; then
    case "${NIX_XD_CHROOT_SELINUX:-keep}" in
      keep) ;;
      userns) printf 'SecurityLabelType=container_userns_t\n' ;;
      disabled) printf 'SecurityLabelDisable=true\n' ;;
      *) return 2 ;;
    esac
    local specs=() spec name chroot_volume seen=' ' seen_volumes=' '
    read -r -a specs <<< "$NIX_XD_INITIAL_CHROOT_STORES"
    for spec in ${specs[@]+"${specs[@]}"}; do
      [[ $spec == *=* ]] || return 2
      name=${spec%%=*}; chroot_volume=${spec#*=}
      [[ $name =~ ^[a-z][a-z0-9-]{0,39}$ && $chroot_volume =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || return 2
      [[ $chroot_volume != "$builder_store_volume" && $seen != *" $name "* && $seen_volumes != *" $chroot_volume "* ]] || return 2
      seen="$seen$name "
      seen_volumes="$seen_volumes$chroot_volume "
      printf 'Volume=%s:/stores/%s\n' "$chroot_volume" "$name"
    done
    printf 'Unmask=/proc/*\n'
    [[ ${NIX_XD_INITIAL_SECCOMP_PATH:-} == "$HOME"/.config/nix-xd/seccomp/"$scope"-nix-chroot.json ]] || return 2
    printf 'SeccompProfile=%s\n' "$NIX_XD_INITIAL_SECCOMP_PATH"
  fi
  printf 'Exec=sleep infinity\n\n[Service]\n'
  for ((i=0;i<builder_peer_count;i++)); do
    volume="${builder_peer_volumes[i]}"
    printf 'ExecStartPre=/usr/bin/podman volume exists %s\n' "$volume"
  done
  printf 'Restart=on-failure\nTimeoutStartSec=300\n\n[Install]\nWantedBy=default.target\n'
}

# Provider-neutral CLI prefix: podman [--connection ...] or container.
builder_volume_create() {
  local scope="$1" name="$2" role="$3"
  shift 3
  local lifecycle="${NIX_XD_LIFECYCLE:-reusable}"
  [[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ && "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ && "$role" =~ ^[a-z][a-z0-9-]*$ ]] || return 2
  [[ "$lifecycle" == reusable || "$lifecycle" == disposable ]] || return 2
  "$@" volume create --label io.nix-xd.managed=true --label io.nix-xd.schema=1 \
    --label "io.nix-xd.scope=$scope" --label "io.nix-xd.role=$role" \
    --label "io.nix-xd.lifecycle=$lifecycle" "$name"
}
