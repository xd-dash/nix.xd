#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

mode="${1:?Expected bootstrap, auth-start, auth-finish, auth-refresh or source-sync}"
smoke="${NIX_XD_NATIVE_BINARY:?Select native Smoke binary from Nix store}"
[[ "$smoke" =~ ^/nix/store/[a-z0-9]{32}-smoke$ && -x "$smoke" ]] || exit 2
[[ "$(uname -s)" == Linux && "$(id -u)" == 1000 ]] || exit 2
[[ "$HOME" == /home/ghxd && -d "$HOME" && -w "$HOME" ]] || exit 2
credentials=/run/nix-xd/ghxd
[[ -d "$credentials" && -r "$credentials" ]] || exit 2
if [[ "$mode" != source-sync ]]; then
  [[ -w "$credentials" ]] || exit 2
fi
identity="$credentials/identity.txt"
ciphertext="$credentials/token.sops.json"
pending="$credentials/device-request.json"
client_id_file="$credentials/client-id"
mkdir -p "$HOME/.cache/ghxd"
export GOCACHE="$HOME/.cache/ghxd/go-build" GOMODCACHE="$HOME/.cache/ghxd/go-mod"
export CGO_ENABLED=0 GOOS=linux
export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1
if [[ -e "$identity" ]]; then
  [[ ! -L "$identity" && -s "$identity" && "$(stat -c %a "$identity")" == 600 ]] || exit 1
fi

encrypt_token() {
  local input=$1 output recipient
  [[ -f "$identity" ]] || exit 1
  python3 - "$input" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))
if not isinstance(v,dict) or not isinstance(v.get("access_token"),str) or not v["access_token"]:
    raise SystemExit("OAuth response missing access_token")
PY
  output="$(mktemp "$credentials/.credential.XXXXXXXX")"
  recipient="$(age-keygen -y "$identity")"
  if ! sops --encrypt --age "$recipient" --input-type json --output-type json "$input" > "$output"; then
    rm -f -- "$output"
    return 1
  fi
  chmod 0600 "$output"
  mv -f -- "$output" "$ciphertext"
}

case "$mode" in
  bootstrap)
    "$smoke" ghxd bootstrap
    echo 'GHXD_BOOTSTRAP=passed'
    ;;
  auth-start)
    [[ ! -e "$ciphertext" && ! -e "$pending" ]] || {
      echo 'GHXD_AUTH=already-initialized-or-pending; refusing overwrite' >&2; exit 1;
    }
    client="${NIX_XD_GHXD_CLIENT_ID:?Public GitHub OAuth/GitHub App client ID required}"
    [[ "$client" =~ ^[A-Za-z0-9._-]{8,128}$ ]] || exit 2
    if [[ ! -e "$identity" ]]; then
      age-keygen -o "$identity" >/dev/null 2>&1
      chmod 0600 "$identity"
    fi
    request="$("$smoke" ghxd auth device "$client")"
    python3 -c 'import json,sys;d=json.load(sys.stdin);assert d.get("device_code") and d.get("user_code") and d.get("verification_uri")' <<< "$request"
    printf '%s\n' "$request" > "$pending"
    chmod 0600 "$pending"
    printf '%s\n' "$client" > "$client_id_file"
    chmod 0600 "$client_id_file"
    python3 - "$pending" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print("GHXD_AUTH=awaiting-browser-approval")
print("GHXD_VERIFY_URL="+d["verification_uri"])
print("GHXD_USER_CODE="+d["user_code"])
PY
    ;;
  auth-finish)
    [[ -s "$pending" && -s "$client_id_file" && ! -e "$ciphertext" ]] || {
      echo 'No pending device authorization or credential already present' >&2; exit 1;
    }
    client="$(cat "$client_id_file")"
    device_code="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["device_code"])' "$pending")"
    scratch="$(mktemp -d /tmp/ghxd-oauth.XXXXXXXX)"
    trap 'rm -rf -- "$scratch"' EXIT
    "$smoke" ghxd auth poll "$client" "$device_code" > "$scratch/token.json"
    encrypt_token "$scratch/token.json"
    rm -f -- "$pending"
    echo 'GHXD_AUTH=passed persistence=sops-age volume=dedicated'
    ;;
  auth-refresh)
    [[ -s "$ciphertext" && -s "$identity" && -s "$client_id_file" ]] || exit 1
    scratch="$(mktemp -d /tmp/ghxd-refresh.XXXXXXXX)"
    trap 'rm -rf -- "$scratch"' EXIT
    SOPS_AGE_KEY_FILE="$identity" sops --decrypt --input-type json --output-type json "$ciphertext" > "$scratch/previous.json"
    refresh_token="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("refresh_token",""))' "$scratch/previous.json")"
    [[ -n "$refresh_token" ]] || {
      echo 'OAuth response has no refresh token; new device authorization is required' >&2; exit 1;
    }
    client="$(cat "$client_id_file")"
    "$smoke" ghxd auth refresh "$client" "$refresh_token" > "$scratch/updated.json"
    encrypt_token "$scratch/updated.json"
    echo 'GHXD_AUTH_REFRESH=passed persistence=sops-age'
    ;;
  source-sync)
    [[ -s "$ciphertext" && -s "$identity" ]] || {
      echo 'GHXD_AUTH=missing; authorize with auth-start/auth-finish first' >&2; exit 1;
    }
    [[ -d /data/ghxd && -w /data/ghxd ]] || exit 1
    scratch="$(mktemp -d /tmp/ghxd-source.XXXXXXXX)"
    trap 'rm -rf -- "$scratch"; unset GH_TOKEN' EXIT
    SOPS_AGE_KEY_FILE="$identity" sops --decrypt --input-type json --output-type json "$ciphertext" > "$scratch/token.json"
    GH_TOKEN="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["access_token"])' "$scratch/token.json")"
    [[ -n "$GH_TOKEN" ]] || exit 1
    export GH_TOKEN
    rows="$(python3 -c '
import json,re,sys
d=json.load(sys.stdin)
assert d.get("schema")==1 and isinstance(d.get("sources"),dict)
for name,item in sorted(d["sources"].items()):
    repo=item["repository"]; sha=item["revision"]; dest=item["checkout"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo): raise SystemExit("Invalid repo")
    if not re.fullmatch(r"[0-9a-f]{40}",sha): raise SystemExit("Invalid revision")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}",dest): raise SystemExit("Invalid checkout")
    print("\t".join((repo,sha,dest)))
')"
    [[ -n "$rows" ]] || { echo 'Empty source manifest' >&2; exit 2; }
    while IFS=$'\t' read -r repo sha checkout; do
      [[ -n "$repo" ]] || continue
      dest="/data/ghxd/$checkout"
      if [[ -e "$dest" ]]; then
        [[ -d "$dest/.git" || -f "$dest/.git" ]] || exit 1
        [[ "$(git -C "$dest" rev-parse HEAD)" == "$sha" ]] || {
          echo "GHXD_SOURCE=conflict checkout=$checkout" >&2; exit 1;
        }
        [[ -z "$(git -C "$dest" status --porcelain --untracked-files=no)" ]] || exit 1
      else
        "$smoke" ghxd worktree seed --repository "$repo" --sha "$sha" \
          --destination "$dest" --object-root /data/ghxd/objects
      fi
      printf 'GHXD_SOURCE=passed repo=%s sha=%s checkout=%s\n' "$repo" "$sha" "$checkout"
    done <<< "$rows"
    echo 'GHXD_SOURCE_SYNC=passed'
    ;;
  *)
    echo "Unknown GHXD mode: $mode" >&2
    exit 2
    ;;
esac
