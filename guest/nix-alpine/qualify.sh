set -eu
[ "$(id -u)" = 1000 ]
[ "$(cat /etc/alpine-release)" = 3.23.0 ]
[ "$HOME" = /home/nixuser ]
grep -Eq ' /nix/store ro(,| )' /proc/self/mountinfo
grep -Eq ' /nix/var rw(,| ).* - tmpfs ' /proc/self/mountinfo
grep -Eq ' /home/nixuser rw(,| ).* - tmpfs ' /proc/self/mountinfo
[ -x /bin/busybox ]
[ -L /usr/local/bin/nix ]
printf 'NESTED_NIX_ALPINE_BASE=%s uid=%s\n' "$(cat /etc/alpine-release)" "$(id -u)"
nix --version
# Register metadata in the guest database; package contents stay on read-only 9P.
nix-store --load-db < @registration@/registration
nix-store --query --requisites @hello@ >/tmp/closure.txt
grep -Fx @hello@ /tmp/closure.txt
nix path-info @hello@
[ "$(nix eval --offline --impure --raw --expr builtins.currentSystem)" = @system@ ]
[ "$(hello)" = 'Hello, world!' ]
printf 'guest-local\n' > "$HOME/runtime-probe"
printf 'guest-local\n' > /nix/var/runtime-probe
[ "$(cat "$HOME/runtime-probe")" = guest-local ]
[ "$(cat /nix/var/runtime-probe)" = guest-local ]
printf 'NESTED_NIX_ALPINE_STORE=read-only-9p metadata=guest-local\n'
printf 'NESTED_NIX_ALPINE_RESULT=passed\n'
