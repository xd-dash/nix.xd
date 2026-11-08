#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
modules="${NIX_XD_QUALIFY_MODULES:-}"
[[ -n "$modules" ]] || { echo 'QUALIFY_MODULES is empty' >&2; exit 2; }
[[ "$modules" =~ ^[a-z][a-z0-9-]*(,[a-z][a-z0-9-]*)*$ ]] || {
  echo 'QUALIFY_MODULES must be a comma-delimited list of safe module names' >&2
  exit 2
}
IFS=, read -r -a names <<< "$modules"
for module in "${names[@]}"; do
  path="$repo/qualifiers/modules/$module.sh"
  [[ -f "$path" ]] || { printf 'Unknown qualification module: %s\n' "$module" >&2; exit 2; }
  printf 'QUALIFY_MODULE_START=%s\n' "$module"
  bash "$path"
  printf 'QUALIFY_MODULE_PASS=%s\n' "$module"
done
printf 'QUALIFY_MODULES_RESULT=passed modules=%s\n' "$modules"
