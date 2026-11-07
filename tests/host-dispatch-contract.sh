#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat >"$tmp/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$NIX_XD_TEST_RECORD"
MOCK
cat >"$tmp/bin/podman" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$NIX_XD_TEST_RECORD"
MOCK
chmod +x "$tmp/bin/systemctl" "$tmp/bin/podman"
export PATH="$tmp/bin:$PATH" NIX_XD_TEST_RECORD="$tmp/calls"
export NIX_XD_PROVIDER=podman NIX_XD_SCOPE=nix-xd-smoke-podman
export NIX_XD_HOST_ALLOWED_ACTIONS=status
bash "$root/bin/nix-xd-host-dispatch" status >/dev/null
grep -Eq -- '(--user is-active|systemctl --user is-active) nix-xd-smoke-podman.service
if bash "$root/bin/nix-xd-host-dispatch" restart >/dev/null 2>&1; then
  echo 'Unexpected privileged action accepted' >&2; exit 1
fi
if bash "$root/bin/nix-xd-host-dispatch" exec >/dev/null 2>&1; then
  echo 'Unexpected shell dispatch accepted' >&2; exit 1
fi
if NIX_XD_SCOPE='../admin' bash "$root/bin/nix-xd-host-dispatch" status >/dev/null 2>&1; then
  echo 'Unsafe scope accepted' >&2; exit 1
fi
if bash "$root/bin/nix-xd-host-dispatch" status --extra >/dev/null 2>&1; then
  echo 'Extra arguments accepted' >&2; exit 1
fi
NIX_XD_HOST_ALLOWED_ACTIONS=status,restart bash "$root/bin/nix-xd-host-dispatch" restart >/dev/null
grep -Eq -- '(--user restart|systemctl --user restart) nix-xd-smoke-podman.service
echo 'PASS: local host dispatch action and scope boundaries'
 "$tmp/calls"
if bash "$root/bin/nix-xd-host-dispatch" restart >/dev/null 2>&1; then
  echo 'Unexpected privileged action accepted' >&2; exit 1
fi
if bash "$root/bin/nix-xd-host-dispatch" exec >/dev/null 2>&1; then
  echo 'Unexpected shell dispatch accepted' >&2; exit 1
fi
if NIX_XD_SCOPE='../admin' bash "$root/bin/nix-xd-host-dispatch" status >/dev/null 2>&1; then
  echo 'Unsafe scope accepted' >&2; exit 1
fi
if bash "$root/bin/nix-xd-host-dispatch" status --extra >/dev/null 2>&1; then
  echo 'Extra arguments accepted' >&2; exit 1
fi
NIX_XD_HOST_ALLOWED_ACTIONS=status,restart bash "$root/bin/nix-xd-host-dispatch" restart >/dev/null
grep -Fxq -- '--user restart nix-xd-smoke-podman.service' "$tmp/calls"
echo 'PASS: local host dispatch action and scope boundaries'
 "$tmp/calls"
echo 'PASS: local host dispatch action and scope boundaries'
 "$tmp/calls"
if bash "$root/bin/nix-xd-host-dispatch" restart >/dev/null 2>&1; then
  echo 'Unexpected privileged action accepted' >&2; exit 1
fi
if bash "$root/bin/nix-xd-host-dispatch" exec >/dev/null 2>&1; then
  echo 'Unexpected shell dispatch accepted' >&2; exit 1
fi
if NIX_XD_SCOPE='../admin' bash "$root/bin/nix-xd-host-dispatch" status >/dev/null 2>&1; then
  echo 'Unsafe scope accepted' >&2; exit 1
fi
if bash "$root/bin/nix-xd-host-dispatch" status --extra >/dev/null 2>&1; then
  echo 'Extra arguments accepted' >&2; exit 1
fi
NIX_XD_HOST_ALLOWED_ACTIONS=status,restart bash "$root/bin/nix-xd-host-dispatch" restart >/dev/null
grep -Fxq -- '--user restart nix-xd-smoke-podman.service' "$tmp/calls"
echo 'PASS: local host dispatch action and scope boundaries'
