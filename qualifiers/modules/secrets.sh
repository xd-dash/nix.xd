#!/usr/bin/env bash
set -Eeuo pipefail

provider="${NIX_XD_PROVIDER:-podman}"
machine="${NIX_XD_MACHINE:-coreos-arm64}"
scope="${NIX_XD_SCOPE:-nix-xd-arm}"
system="${NIX_XD_SYSTEM:-aarch64-linux}"
[[ "$scope" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || { echo 'Invalid scope' >&2; exit 2; }
[[ "$machine" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Invalid machine' >&2; exit 2; }
[[ "$system" == aarch64-linux || "$system" == x86_64-linux ]] || { echo 'Invalid system' >&2; exit 2; }
[[ "$provider" == podman ]] || { echo 'Secrets qualifier currently requires Podman provider' >&2; exit 2; }

podman machine inspect "$machine" >/dev/null
image_arch="$(podman --connection "$machine" exec "$scope" uname -m)" ||
  { echo 'Nix-Alpine runtime not found' >&2; exit 1; }
case "$system:$image_arch" in
  aarch64-linux:aarch64|aarch64-linux:arm64|x86_64-linux:x86_64) ;;
  *) printf 'Runtime architecture mismatch: system=%s image=%s\n' "$system" "$image_arch" >&2; exit 1 ;;
esac

printf 'SECRETS_QUALIFY_RUNTIME=podman machine=%s scope=%s system=%s\n' "$machine" "$scope" "$system"
# The script itself contains no credentials and is delivered by stdin.
# The private age key and plaintext are generated inside the runtime and
# deleted on exit. nix shell only installs age and sops executable closures.
podman --connection "$machine" exec -i "$scope" \
  nix --extra-experimental-features 'nix-command flakes' shell \
    nixpkgs#age nixpkgs#sops --command bash -se <<'RUNTIME'
set -Eeuo pipefail
umask 077
scratch="$(mktemp -d /tmp/nix-xd-secrets.XXXXXXXX)"
cleanup() { rm -rf -- "$scratch"; }
trap cleanup EXIT
case "$(readlink -f "$scratch")" in
  /nix/store/*) echo 'Runtime scratch unexpectedly located in Nix store' >&2; exit 1 ;;
  /tmp/nix-xd-secrets.*) ;;
  *) echo 'Unsafe runtime scratch path' >&2; exit 1 ;;
esac
key="$scratch/keys.txt"
plaintext="$scratch/plain.json"
ciphertext="$scratch/enc.json"
roundtrip="$scratch/dec.json"
age-keygen -o "$key" 2>"$scratch/age-keygen.stderr"
recipient="$(age-keygen -y "$key")"
[[ "$recipient" == age1* ]] || { echo 'Unable to derive public age recipient' >&2; exit 1; }
[[ "$(stat -c %a "$key")" == 600 ]] || { echo 'Private age key permissions not 0600' >&2; exit 1; }
printf '%s\n' '{"sandbox":"nix-xd-qualification","roundtrip":true}' >"$plaintext"
sops --encrypt --age "$recipient" --input-type json --output-type json "$plaintext" >"$ciphertext"
SOPS_AGE_KEY_FILE="$key" sops --decrypt --input-type json --output-type json "$ciphertext" >"$roundtrip"
cmp -s "$plaintext" "$roundtrip" || { echo 'SOPS roundtrip mismatch' >&2; exit 1; }
grep -q '"sops"' "$ciphertext" || { echo 'Missing SOPS metadata' >&2; exit 1; }
if grep -q 'nix-xd-qualification' "$ciphertext"; then
  echo 'Plaintext leaked into encrypted SOPS document' >&2
  exit 1
fi
printf 'SECRETS_AGE_IDENTITY=passed mode=0600 location=runtime-scratch\n'
printf 'SECRETS_SOPS_ROUNDTRIP=passed\n'
printf 'SECRETS_NIX_STORE_ISOLATION=passed private-material-in-store=no\n'
RUNTIME
printf 'SECRETS_QUALIFY_RESULT=passed\n'
