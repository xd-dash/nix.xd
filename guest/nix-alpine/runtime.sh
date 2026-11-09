set -eu
@check@/bin/nix-alpine-qualify
: > "$XDG_RUNTIME_DIR/ready"
printf 'NIX_ALPINE_RUNTIME_READY=passed\n'
exec /bin/sleep 2147483647
