#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
project="$temp/projects/fixture"
mkdir -p "$project/local/example/host-actions"
cat > "$project/local/example/host-actions/check.sh" <<'ACTION'
#!/usr/bin/env bash
set -Eeuo pipefail
test "$NIX_XD_SELECTED_PROJECT_REV" = "$(git -C "$NIX_XD_HOST_WORKSPACES/fixture" rev-parse HEAD)"
test "$NIX_XD_SELECTED_PROJECT_FLAKE" = /workspaces/fixture/local/example
printf 'GENERIC_HOST_ACTION=passed\n'
ACTION
git -C "$project" init -q
git -C "$project" config user.email fixture@example.invalid
git -C "$project" config user.name Fixture
git -C "$project" add .
git -C "$project" commit -qm fixture
sha="$(git -C "$project" rev-parse HEAD)"
output="$(NIX_XD_HOST_WORKSPACES="$temp/projects" NIX_XD_PROJECT=fixture NIX_XD_APPLICATION=example NIX_XD_ACTION=check NIX_XD_PROJECT_REV="$sha" NIX_XD_RUNTIME_REPO="$repo" bash "$repo/bin/nix-xd-project-host-run")"
grep -Fxq 'GENERIC_HOST_ACTION=passed' <<<"$output"
if NIX_XD_HOST_WORKSPACES="$temp/projects" NIX_XD_PROJECT=fixture NIX_XD_APPLICATION=example NIX_XD_ACTION=check NIX_XD_PROJECT_REV="$(printf '0%.0s' {1..40})" NIX_XD_RUNTIME_REPO="$repo" bash "$repo/bin/nix-xd-project-host-run" >/dev/null 2>&1; then
  echo 'Accepted mismatched immutable project commit' >&2
  exit 1
fi
if NIX_XD_HOST_WORKSPACES="$temp/projects" NIX_XD_PROJECT='../fixture' NIX_XD_APPLICATION=example NIX_XD_ACTION=check NIX_XD_RUNTIME_REPO="$repo" bash "$repo/bin/nix-xd-project-host-run" >/dev/null 2>&1; then
  echo 'Accepted unsafe project selector' >&2
  exit 1
fi
echo 'PROJECT_HOST_ACTION_CONTRACT=passed'
