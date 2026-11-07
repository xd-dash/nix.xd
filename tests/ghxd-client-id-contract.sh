#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/gh" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == 'auth status --hostname github.com' ]]; then exit 0; fi
[[ "${GH_PROMPT_DISABLED:-}" == 1 && "${GIT_TERMINAL_PROMPT:-}" == 0 ]]
[[ "$*" == 'variable get APP_CLIENT_ID --repo xd-dash/huram-abi-master' ]]
printf '%s\n' 'Iv1.synthetic-test-public-id'
MOCK
chmod +x "$tmp/bin/gh"

result="$(env -u GITHUB_CLIENT_ID PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null)"
[[ "$result" == Iv1.synthetic-test-public-id ]] || { echo 'Wrong client ID source' >&2; exit 1; }
result="$(GITHUB_CLIENT_ID=Iv1.explicit-public-client-id PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null)"
[[ "$result" == Iv1.explicit-public-client-id ]] || { echo 'Explicit client ID override failed' >&2; exit 1; }

cat > "$tmp/bin/gh" <<'MOCK'
#!/usr/bin/env bash
exit 1
MOCK
chmod +x "$tmp/bin/gh"
if env -u GITHUB_CLIENT_ID PATH="$tmp/bin:$PATH" bash "$root/bin/nix-xd-ghxd-client-id" </dev/null >"$tmp/out" 2>"$tmp/err"; then
  echo 'Resolver did not fail closed when repository variable unavailable' >&2
  exit 1
fi
[[ ! -s "$tmp/out" ]]
grep -Fq 'GHXD_CLIENT_ID=UNAVAILABLE' "$tmp/err"
! grep -Fq 'GitHub App client ID: ' "$root/bin/nix-xd-qualify-ghxd-auth"
grep -Fq 'bin/nix-xd-ghxd-client-id' "$root/bin/nix-xd-qualify-ghxd-auth"
echo 'PASS: existing gh session resolves huram-abi-master Actions variable without prompts; unavailable credentials fail closed'
