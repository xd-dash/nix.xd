#!/usr/bin/env bash
set -Eeuo pipefail
scope=${1:?scope} flake=${2:?runtime flake}
[[ $scope =~ ^[a-z][a-z0-9-]{0,39}$ && $flake == /workspaces/* && $flake != *..* ]]
[[ $(podman info --format '{{.Host.Security.Rootless}}') == true ]]
oci=$(podman inspect "$scope" --format '{{.OCIConfigPath}}')
[[ -f $oci && -r $oci ]]
# Feed the spec to the existing owner; print only selected security fields.
# Never print the container environment, credentials or the complete OCI spec.
podman exec -i "$scope" nix run --no-write-lock-file "$flake#chroot-store-diagnose" -- --policy < "$oci"
echo BUILDER_NAMESPACE_POLICY_DIAGNOSTIC=collected mutations=false
