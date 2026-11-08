#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/workspaces/nix-alpine/local" "$tmp/bin"
source="$tmp/workspaces/nix-alpine"
git -C "$source" init -q
git -C "$source" config user.email fixture@example.invalid
git -C "$source" config user.name Fixture
git -C "$source" remote add origin https://github.com/dash-xd/nix-alpine.git
cat >"$source/local/Makefile" <<'MK'
.PHONY: bootstrap
bootstrap:
	@printf 'X86_FIXTURE_BOOTSTRAP scope=%s container=%s volume=%s image=%s checkout=%s\n' '$(SCOPE)' '$(CONTAINER)' '$(VOLUME)' '$(IMAGE)' '$(NIX_ALPINE_CHECKOUT)'
MK
touch "$source/local/bootstrap.sh"
git -C "$source" add .
git -C "$source" commit -qm pinned-fixture
rev="$(git -C "$source" rev-parse HEAD)"
cat >"$tmp/bin/podman" <<'PODMAN'
#!/usr/bin/env bash
case "$1" in
  info) echo true ;;
  exec) echo 'nix (Nix) 2.31.2' ;;
  *) echo "Unexpected native Podman command $*" >&2; exit 1 ;;
esac
PODMAN
cat >"$tmp/bin/uname" <<'UNAME'
#!/usr/bin/env bash
case "$1" in
  -s) echo Linux ;;
  -m) echo x86_64 ;;
  *) /usr/bin/uname "$@" ;;
esac
UNAME
chmod +x "$tmp/bin/podman" "$tmp/bin/uname"
export PATH="$tmp/bin:$PATH"
out="$(NIX_XD_PROVIDER=podman NIX_XD_X86_SOURCE="$source" NIX_XD_X86_REV="$rev" NIX_XD_WORKSPACES="$tmp/workspaces" NIX_XD_SCOPE=nix-xd-amd64 NIX_XD_IMAGE=localhost/nix-xd:amd64 bash "$root/bin/nix-xd-bootstrap-amd64")"
[[ "$out" == *'X86_FIXTURE_BOOTSTRAP scope=nix-xd-amd64 container=nix-xd-amd64 volume=nix-xd-amd64-store image=localhost/nix-xd:amd64 checkout=nix-alpine'* ]] ||
  { echo 'x86 bootstrap contract missing scope/volume/image propagation' >&2; exit 1; }
[[ "$out" == *'X86_BOOTSTRAP_RESULT=passed'* ]] ||
  { echo 'x86 bootstrap did not produce result' >&2; exit 1; }
if NIX_XD_PROVIDER=podman NIX_XD_X86_SOURCE="$source" NIX_XD_X86_REV=0000000000000000000000000000000000000000 NIX_XD_WORKSPACES="$tmp/workspaces" bash "$root/bin/nix-xd-bootstrap-amd64" >/dev/null 2>&1; then
  echo 'x86 source pin mismatch accepted' >&2; exit 1
fi
for arch in arm64 amd64; do
  output="$(make --no-print-directory -sn -C "$root" bootstrap ARCH="$arch" OS=Darwin)"
  [[ "$output" == *"bootstrap-$arch"* || "$output" == *"$([[ "$arch" == arm64 ]] && echo arm/bootstrap-macos.sh || echo bin/nix-xd-bootstrap-amd64)"* ]] ||
    { echo "Bootstrap target not selected for $arch" >&2; exit 1; }
done
printf 'PASS: Architecture-specific bootstrap adapters preserve common interface and x86 source pin\n'
