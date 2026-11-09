set -eu
[ "$(id -u)" = 1000 ]
[ -f "$XDG_RUNTIME_DIR/ready" ]
grep -Eq ' /nix/store ro(,| )' /proc/self/mountinfo
nix --version
nix path-info @hello@
printf 'NIX_ALPINE_READY=passed\n'
