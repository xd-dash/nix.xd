#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

grep -Fq 'age192f0pk06hur42fxgux3nk92fu6uwleshnvkstsrq4htdwagv8fms4zsvs7' .sops.yaml
grep -Fq 'path_regex:' .sops.yaml
git check-ignore -q .private/sops/ghxd.enc.json

while IFS= read -r file; do
  case "$file" in
    secrets/.gitignore|secrets/README.md) continue ;;
    secrets/*.enc.json|secrets/*.enc.yaml|secrets/*.enc.yml)
      test -f "$file" || { echo 'Tracked ciphertext missing' >&2; exit 1; }
      grep -Eq '"sops"[[:space:]]*:|^sops:' "$file" || {
        echo 'Tracked ciphertext lacks SOPS metadata' >&2; exit 1;
      }
      ;;
    *)
      echo 'Unexpected tracked file in secrets/: refusing potential plaintext' >&2
      exit 1
      ;;
  esac
done < <(git ls-files secrets/)

if git ls-files | grep -Eq '(^|/)(identity\.txt|age-key\.txt|private\.key|secrets\.env)$'; then
  echo 'Potential private key or plaintext environment file tracked' >&2
  exit 1
fi

echo 'PASS: only public recipient/config and SOPS ciphertext are permitted as tracked secrets'
