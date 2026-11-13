set -eu
@check@/bin/nix-alpine-qualify
: > "$XDG_RUNTIME_DIR/ready"
printf 'NIX_ALPINE_RUNTIME_READY=passed\n'
/bin/sleep 2147483647 &
runtime_pid=$!
trap 'kill "$runtime_pid" 2>/dev/null || :; wait "$runtime_pid" 2>/dev/null || :; exit 0' TERM INT
wait "$runtime_pid"
