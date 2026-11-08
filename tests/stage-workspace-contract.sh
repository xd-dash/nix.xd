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
if [[ "$*" == *" test -d /workspaces" ]]; then exit 1; fi
exit 0
MOCK
chmod +x "$tmp/bin/podman"
export PATH="$tmp/bin:$PATH"
export STAGE_TEST_RECORD="$tmp/record"
NIX_XD_PROVIDER=podman NIX_XD_SCOPE=nix-xd-arm NIX_XD_MACHINE=selected-machine \
  NIX_XD_WORKSPACES="$tmp/ws" NIX_XD_CHECKOUT=project bash "$repo/bin/nix-xd-task" stage
grep -Fq -- "--connection selected-machine exec nix-xd-arm --user" "$tmp/record" && {
  echo "Incorrect Podman exec argument ordering" >&2; exit 1;
}
grep -Fq -- "--connection selected-machine exec --user 0 nix-xd-arm install -d -m 0755 -o 1000 -g 1000 /workspaces" "$tmp/record"
grep -Fq -- "--connection selected-machine cp" "$tmp/record"
grep -Fq -- "--connection selected-machine exec nix-xd-arm mkdir -p /workspaces/project" "$tmp/record"
echo "PASS: staging initializes the workspace root once and uses the selected Podman Machine"
