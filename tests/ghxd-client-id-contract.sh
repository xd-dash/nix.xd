#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == --connection && "$2" == podman-machine-default ]]
shift 2
[[ "$1" == exec && "$2" == nix-xd-smoke-podman ]]
shift 2
[[ "$1" == nix && "$2" == develop ]]
[[ "$3" == /workspaces/nix-alpine/nix-alpine/toolbox#security && "$4" == -c ]]
shift 4
[[ "$1" == gh ]]
shift
case "$*" in
  'auth status --hostname github.com') exit 0 ;;
  'api repos/xd-dash/huram-abi-master/environments/master/variables/APP_CLIENT_ID --jq .value') printf '%s\n' 'Iv1.synthetic-public-client-id' ;;
  *) exit 39 ;;
esac
MOCK
chmod +x "$tmp/bin/podman"

result="$(env -u GITHUB_CLIENT_ID NIX_XD_MACHINE=podman-machine-default NIX_XD_SCOPE=nix-xd-smoke-podman PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null)"
[[ "$result" == Iv1.synthetic-public-client-id ]]
# Force an environment 404 and prove the repository-level fallback remains usable.
cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == --connection && "$2" == podman-machine-default ]]
shift 2
[[ "$1" == exec && "$2" == nix-xd-smoke-podman ]]
shift 2
[[ "$1" == nix && "$2" == develop ]]
shift 4
[[ "$1" == gh ]]
shift
case "$*" in
  'auth status --hostname github.com') exit 0 ;;
  'api repos/xd-dash/huram-abi-master/environments/master/variables/APP_CLIENT_ID --jq .value') echo 'HTTP 404 Not Found' >&2; exit 1 ;;
  'api repos/xd-dash/huram-abi-master/actions/variables/APP_CLIENT_ID --jq .value') printf '%s\\n' 'Iv1.repo-fallback-id' ;;
  *) exit 39 ;;
esac
MOCK
chmod +x "$tmp/bin/podman"
fallback="$(env -u GITHUB_CLIENT_ID PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null 2>"$tmp/fallback-err")"
[[ "$fallback" == Iv1.repo-fallback-id ]]
grep -Fq 'GHXD_CLIENT_ID_PROBE=environment' "$tmp/fallback-err"

result="$(GITHUB_CLIENT_ID=Iv1.explicit-client-id PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null)"
[[ "$result" == Iv1.explicit-client-id ]]

cat > "$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
exit 27
MOCK
chmod +x "$tmp/bin/podman"
if env -u GITHUB_CLIENT_ID PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null >"$tmp/out" 2>"$tmp/err"; then
  echo 'Client ID discovery accepted a failed Nix guest authentication' >&2
  exit 1
fi
[[ ! -s "$tmp/out" ]]
grep -Fq 'GHXD_CLIENT_ID=UNAVAILABLE' "$tmp/err"
! grep -Fq 'brew' "$root/bin/nix-xd-ghxd-client-id"
grep -Fq 'toolbox#security' "$root/bin/nix-xd-ghxd-client-id"
grep -Fq 'bin/nix-xd-ghxd-client-id' "$root/bin/nix-xd-qualify-ghxd-auth"
echo 'PASS: gh is supplied by Nix-Alpine flake, not host Homebrew; no client-ID prompt'
