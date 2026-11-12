#!/usr/bin/env bash
set -Eeuo pipefail
scope="${1:?qualification scope}"
image="${2:?cached image}"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,25}$ ]] || exit 2
[[ "$image" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]] || exit 2
[[ "$(podman info --format '{{.Host.Security.Rootless}}')" == true ]] || { echo 'Rootless Podman required' >&2; exit 1; }
[[ "$(getenforce)" == Enforcing ]] || { echo 'SELinux enforcing required for isolation gate' >&2; exit 1; }
podman image exists "$image" || { echo "Missing cached image: $image" >&2; exit 1; }
secret="$scope-secret"
input="$scope-input"
evidence="$scope-evidence"
owner="$scope-owner"
reader="$scope-reader"
outsider="$scope-outsider"
for v in "$secret" "$input" "$evidence"; do
  ! podman volume exists "$v" || { echo "Existing fixture volume $v" >&2; exit 1; }
done
for c in "$owner" "$reader" "$outsider"; do
  ! podman container exists "$c" || { echo "Existing fixture container $c" >&2; exit 1; }
done
volumes=()
containers=()
cleanup() {
  local rc=$? c v
  trap - EXIT
  for c in "${containers[@]}"; do podman rm -f "$c" >/dev/null 2>&1 || rc=1; done
  for v in "${volumes[@]}"; do podman volume rm "$v" >/dev/null 2>&1 || rc=1; done
  if ((rc == 0)); then echo 'GRANTS_ISOLATION_CLEANUP=passed'; else echo 'GRANTS_ISOLATION_CLEANUP=failed' >&2; fi
  exit "$rc"
}
trap cleanup EXIT
for v in "$secret" "$input" "$evidence"; do
  podman volume create --label io.nix-xd.managed=true --label io.nix-xd.role=qualification-fixture --label io.nix-xd.lifecycle=disposable --label "io.nix-xd.scope=$scope" "$v" >/dev/null
  volumes+=("$v")
done
# The volumes are brand new disposable fixtures: :U is safe here, but must
# never be applied automatically to persistent secret or Nix store volumes.
common=(--pull=never --network none --read-only --cap-drop all --user 1000:1000)
podman run --rm "${common[@]}" --uidmap 0:32768:8192 --gidmap 0:32768:8192 \
  --security-opt label=type:container_t \
  -v "$secret:/secrets:z,U,nocreate" -v "$input:/input:z,U,nocreate" \
  -v "$evidence:/evidence:z,U,nocreate" --entrypoint /bin/sh "$image" -ec '
    umask 077
    printf "age-secret-fixture-only" > /secrets/identity
    chmod 0700 /secrets && chmod 0600 /secrets/identity
    printf "input-fixture" > /input/value
    chmod 0755 /input && chmod 0644 /input/value
    chmod 0777 /evidence
  '
podman run --rm "${common[@]}" --uidmap 0:32768:8192 --gidmap 0:32768:8192 \
  --security-opt label=type:container_t \
  -v "$secret:/secrets:ro,nocreate" -v "$input:/input:ro,nocreate" \
  -v "$evidence:/evidence:rw,nocreate" --entrypoint /bin/sh "$image" -ec '
    test "$(cat /secrets/identity)" = age-secret-fixture-only
    test "$(cat /input/value)" = input-fixture
    if touch /secrets/wrong 2>/dev/null; then exit 1; fi
    if touch /input/wrong 2>/dev/null; then exit 1; fi
    printf "fixture-evidence" > /evidence/result
    test "$(cat /evidence/result)" = fixture-evidence
  '
echo 'GRANTS_AUTHORIZED_READER=passed secrets=ro input=ro evidence=rw'
podman run --rm "${common[@]}" --uidmap 0:40960:8192 --gidmap 0:40960:8192 \
  --security-opt label=type:container_t \
  -v "$secret:/secrets:ro,nocreate" -v "$input:/input:ro,nocreate" \
  --entrypoint /bin/sh "$image" -ec '
    if cat /secrets/identity >/dev/null 2>&1; then exit 1; fi
    test "$(cat /input/value)" = input-fixture
    if touch /input/wrong 2>/dev/null; then exit 1; fi
  '
echo 'GRANTS_UNAUTHORIZED_SECRET_READ=denied boundary=dac-and-userns'
echo 'GRANTS_ISOLATION_RESULT=passed mode=disposable no_existing_volumes_modified=true'
