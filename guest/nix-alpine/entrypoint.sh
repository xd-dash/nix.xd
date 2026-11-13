#!/bin/sh
set -eu
[ "$(id -u)" = 1000 ]
umask 077
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
[ -O "$HOME" ] && [ -O "$XDG_RUNTIME_DIR" ]
chmod 0700 "$HOME" "$XDG_RUNTIME_DIR"
exec "$@"
