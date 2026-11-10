#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash -n bin/nix-xd-store-isolation
command -v jq >/dev/null || { echo 'jq required for isolated-store contract' >&2; exit 1; }
dry="$(make -sn store-isolation-check ARCH=arm64 PROVIDER=container)"
[[ "$dry" == *"bin/nix-xd-store-isolation"* ]] || exit 1
! grep -Eq 'volume (rm|delete)|nix store gc|nix-store --gc|rm -rf /nix' bin/nix-xd-store-isolation

mock="$(mktemp -d)"
trap 'rm -rf "$mock"' EXIT
cat >"$mock/container" <<'FAKE'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$1:$2" in
  volume:inspect)
    printf '[{"id":"%s"}]\n' "$3"
    ;;
  inspect:*)
    scope="$2"
    volume="$scope-store"
    if [[ "${MOCK_CONFLICT:-0}" == 1 && "$scope" == nix-xd-grumble-arm ]]; then
      volume=nix-xd-arm-store
    fi
    printf '[{"configuration":{"mounts":[{"type":"volume","name":"%s","destination":"/nix"}]}}]\n' "$volume"
    ;;
  exec:*)
    [[ "$3" == sh || "$3" == nix ]] || exit 3
    ;;
  *) exit 4 ;;
esac
FAKE
chmod +x "$mock/container"
result="$(PATH="$mock:$PATH" NIX_XD_PROVIDER=container bash bin/nix-xd-store-isolation)"
grep -Fq 'STORE_ISOLATION_RESULT=passed' <<<"$result" || exit 1
if PATH="$mock:$PATH" NIX_XD_PROVIDER=container MOCK_CONFLICT=1 bash bin/nix-xd-store-isolation >/dev/null 2>&1; then
  echo 'Wrong named volume must fail closed' >&2
  exit 1
fi
if PATH="$mock:$PATH" NIX_XD_PROVIDER=container NIX_XD_ISOLATION_SECONDARY=nix-xd-arm bash bin/nix-xd-store-isolation >/dev/null 2>&1; then
  echo 'Identical writer scopes must fail closed' >&2
  exit 1
fi
echo 'PASS: independent Nix stores reject shared mounts, duplicates and destructive operations'
