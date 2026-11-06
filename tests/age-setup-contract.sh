#!/usr/bin/env bash
set -euo pipefail
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/repo/bin" "$tmp/mock" "$tmp/home"
cp "$source_root/bin/nix-xd-age-setup" "$tmp/repo/bin/"
cat >"$tmp/mock/uname" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == -s ]] && echo Darwin || /usr/bin/uname "$@"
MOCK
cat >"$tmp/mock/age-keygen" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  -o) printf '%s\n' 'AGE-SECRET-KEY-SYNTHETIC-DO-NOT-USE' > "$2" ;;
  -y) printf '%s\n' 'age1syntheticpublicrecipient' ;;
  *) exit 2 ;;
esac
MOCK
chmod +x "$tmp/mock/"*
export PATH="$tmp/mock:$PATH" HOME="$tmp/home"
bash "$tmp/repo/bin/nix-xd-age-setup" > "$tmp/setup.log"
test -f "$HOME/.config/nix.xd/age/keys.txt"
[[ "$(stat -c %a "$HOME/.config/nix.xd/age/keys.txt")" == 600 ]]
grep -Fq 'age1syntheticpublicrecipient' "$tmp/repo/.private/sops/.sops.yaml"
if grep -Fq 'AGE-SECRET-KEY-SYNTHETIC' "$tmp/setup.log"; then
  echo 'Age private identity leaked to diagnostic output' >&2; exit 1
fi
before="$(sha256sum "$HOME/.config/nix.xd/age/keys.txt")"
bash "$tmp/repo/bin/nix-xd-age-setup" >>"$tmp/setup.log"
after="$(sha256sum "$HOME/.config/nix.xd/age/keys.txt")"
[[ "$before" == "$after" ]] || { echo 'Age identity was overwritten' >&2; exit 1; }
echo 'PASS: age identity is mode 0600, reused, outside workspace, never printed'
