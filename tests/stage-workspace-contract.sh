#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/ws/project"
git -C "$tmp/ws/project" init -q
git -C "$tmp/ws/project" -c user.name=Fixture -c user.email=fixture@example.invalid commit --allow-empty -qm fixture
cat >"$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
printf "%s\n" "$*" >> "$STAGE_TEST_RECORD"
if [[ "${3:-}" == cp ]]; then cat "$4/.nix-xd-source-revision" > "$STAGE_TEST_REV"; fi
if [[ "$*" == *" uname -m" ]]; then echo aarch64; exit 0; fi
if [[ "$*" == *" test -d /workspaces" ]]; then exit 1; fi
exit 0
MOCK
cat >"$tmp/bin/uname" <<'MOCK_UNAME'
#!/usr/bin/env bash
if [[ "$1" == -s ]]; then echo Darwin; else command /usr/bin/uname "$@"; fi
MOCK_UNAME
chmod +x "$tmp/bin/podman" "$tmp/bin/uname"
export PATH="$tmp/bin:$PATH"
export STAGE_TEST_RECORD="$tmp/record"
export STAGE_TEST_REV="$tmp/revision"
NIX_XD_PROVIDER=podman NIX_XD_SCOPE=nix-xd-arm NIX_XD_MACHINE=selected-machine \
  NIX_XD_WORKSPACES="$tmp/ws" NIX_XD_CHECKOUT=project bash "$repo/bin/nix-xd-task" stage
grep -Fq -- "--connection selected-machine exec nix-xd-arm --user" "$tmp/record" && {
  echo "Incorrect Podman exec argument ordering" >&2; exit 1;
}
grep -Fq -- "--connection selected-machine exec --user 0 nix-xd-arm install -d -m 0755 -o 1000 -g 1000 /workspaces" "$tmp/record"
grep -Fq -- "--connection selected-machine cp" "$tmp/record"
grep -Fq -- "--connection selected-machine exec nix-xd-arm mkdir -p /workspaces/project" "$tmp/record"
[[ "$(cat "$STAGE_TEST_REV")" == "$(git -C "$tmp/ws/project" rev-parse HEAD)" ]]
echo "PASS: staging initializes the workspace root once and uses the selected Podman Machine"

git -C "$tmp/ws/project" worktree add --detach -q "$tmp/ws/linked" HEAD
NIX_XD_PROVIDER=podman NIX_XD_SCOPE=nix-xd-arm NIX_XD_MACHINE=selected-machine \
  NIX_XD_WORKSPACES="$tmp/ws" NIX_XD_CHECKOUT=linked bash "$repo/bin/nix-xd-task" stage
[[ "$(cat "$STAGE_TEST_REV")" == "$(git -C "$tmp/ws/linked" rev-parse HEAD)" ]]
grep -Fq -- "exec nix-xd-arm mkdir -p /workspaces/linked" "$tmp/record"
echo "PASS: staging accepts a linked Git worktree"
