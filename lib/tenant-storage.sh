#!/usr/bin/env bash
# Disposable qualification volumes; the controller only inspects metadata.
tenant_probe_userns() {
  [[ $1 =~ ^user:\[[0-9]+\]$ && $2 =~ ^user:\[[0-9]+\]$ ]] || return 2
  [[ $3 =~ ^[a-z][a-z0-9-]{0,39}$ ]] || return 2
  if [[ $1 == "$2" ]]; then printf 'host\n'; else printf 'container:%s\n' "$3"; fi
}
tenant_volume_name() {
  [[ $1 =~ ^[a-z][a-z0-9-]{0,39}$ && $1 == *-qualify ]] || return 2
  [[ $2 =~ ^[a-z][a-z0-9-]{0,15}$ && $3 =~ ^[a-z][a-z0-9-]{0,15}$ ]] || return 2
  printf '%s-%s-%s\n' "$1" "$2" "$3"
}
tenant_volume_create() {
  local volume
  volume=$(tenant_volume_name "$@") || return
  podman volume create --label io.nix-xd.managed=true --label io.nix-xd.role=tenant-store \
    --label io.nix-xd.lifecycle=disposable --label "io.nix-xd.scope=$1" \
    --label "io.nix-xd.tenant=$2" --label "io.nix-xd.store=$3" "$volume"
}
tenant_volume_remove() {
  local volume identity
  volume=$(tenant_volume_name "$@") || return
  identity=$(podman volume inspect "$volume" --format '{{index .Labels "io.nix-xd.managed"}}|{{index .Labels "io.nix-xd.role"}}|{{index .Labels "io.nix-xd.lifecycle"}}|{{index .Labels "io.nix-xd.scope"}}|{{index .Labels "io.nix-xd.tenant"}}|{{index .Labels "io.nix-xd.store"}}') || return
  [[ $identity == "true|tenant-store|disposable|$1|$2|$3" ]] || {
    echo "TENANT_VOLUME_DELETE=refused volume=$volume reason=identity" >&2; return 1;
  }
  podman volume rm "$volume"
}
