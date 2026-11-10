#!/usr/bin/env python3
"""Qualify existing persistent builders without changing their configuration."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import secrets
import subprocess
import sys

from compose_runtime import Runtime, run
from compositions import require


def mount(container, destination, volume, writable):
    selected = [item for item in container['Mounts'] if item['Destination'] == destination]
    require(len(selected) == 1 and selected[0].get('Name') == volume and selected[0]['RW'] == writable,
            'Unexpected store mount: ' + destination)


def qualify():
    runtime = Runtime(os.environ)
    peer = os.environ.get('NIX_XD_PEER_BUILDER_SCOPE', 'nix-xd-grumble')
    peer_volume = os.environ.get('NIX_XD_PEER_BUILDER_VOLUME', peer + '-store')
    alias = os.environ.get('NIX_XD_PEER_BUILDER_ALIAS', 'agni')
    own_volume = os.environ.get('NIX_XD_STORE_VOLUME', runtime.scope + '-store')
    for value in (peer, alias):
        require(re.fullmatch(r'[a-z][a-z0-9-]{0,39}', value), 'Invalid peer builder or alias')
    require(peer != runtime.scope and peer_volume != own_volume, 'Builders must own different stores')
    for volume in (own_volume, peer_volume):
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', volume), 'Invalid volume')
        run(runtime.podman + ['volume', 'exists', volume], runtime.env, timeout=15)
    containers = json.loads(run(runtime.podman + ['inspect', runtime.scope, peer], runtime.env, True, timeout=30))
    require(len(containers) == 2 and all(item['State']['Running'] for item in containers), 'Both persistent builders must be running')
    mount(containers[0], '/nix', own_volume, True)
    mount(containers[1], '/nix', peer_volume, True)
    mount(containers[1], '/peer/' + alias, own_volume, False)
    token = secrets.token_hex(16)
    directory = '/nix/home/nixuser/.local/state/nix-xd/peer-probe-' + token
    paths = []
    try:
        def add(builder):
            payload = builder + '-' + token
            script = '''set -eu
umask 077
mkdir -p "$1"
printf %s "$2" > "$1/probe"
path=$(nix-store --add "$1/probe")
nix-store --realise --add-root "$1/root" "$path" >/dev/null
printf '%s\\n' "$path"
'''
            path = run(runtime.podman + ['exec', '-i', builder, 'sh', '-se', '--', directory, payload],
                       runtime.env, True, script, timeout=120).strip()
            require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-probe', path), 'Invalid probe output')
            return path
        with ThreadPoolExecutor(max_workers=2) as pool:
            paths = list(pool.map(add, (runtime.scope, peer)))
        require(paths[0] != paths[1], 'Unique builder fixtures resolved to the same output')
        for own, foreign in ((runtime.scope, paths[1]), (peer, paths[0])):
            check = run(runtime.podman + ['exec', own, 'sh', '-ec',
                'if nix-store --check-validity "$1" >/dev/null 2>&1; then exit 1; fi; echo STORE_DATABASE=independent',
                'check', foreign], runtime.env, True, timeout=30)
            require('STORE_DATABASE=independent' in check.splitlines(), 'Store database isolation failed')
        script = '''set -eu
peer=$1 path=$2 payload=$3
[ "$(cat "$peer/store/${path#/nix/store/}")" = "$payload" ]
if (printf x > "$peer/peer-write-$4") 2>/dev/null; then echo 'Peer write unexpectedly succeeded' >&2; exit 1; fi
echo PEER_READ=passed
echo PEER_WRITE=denied
'''
        output = run(runtime.podman + ['exec', '-i', peer, 'sh', '-se', '--', '/peer/' + alias,
            paths[0], runtime.scope + '-' + token, token], runtime.env, True, script, timeout=30)
        print(output, end='', flush=True)
        # Reverse access uses an explicitly read-only reader, preserving the existing owner's Quadlet.
        output = run(runtime.podman + ['run', '--rm', '--pull=never', '--network', 'none',
            '--read-only', '--user', '1000:1000', '--cap-drop', 'all', '--security-opt', 'no-new-privileges',
            '--mount', 'type=volume,src=' + peer_volume + ',dst=/peer/grumble,ro',
            '--entrypoint', '/bin/sh', containers[0]['Image'], '-ec', script, 'peer',
            '/peer/grumble', paths[1], peer + '-' + token, token], runtime.env, True, timeout=60)
        print(output, end='', flush=True)
        after = json.loads(run(runtime.podman + ['inspect', runtime.scope, peer], runtime.env, True, timeout=30))
        require([item['Id'] for item in containers] == [item['Id'] for item in after] and
                all(item['State']['Running'] for item in after), 'A persistent builder changed during qualification')
    finally:
        for builder in (runtime.scope, peer):
            run(runtime.podman + ['exec', builder, 'rm', '-rf', '--', directory], runtime.env, timeout=30)
    print('BUILDER_STORE_RESULT=passed databases=independent peer_mounts=read-only builders=unchanged', flush=True)


if __name__ == '__main__':
    try: qualify()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Builder store qualification error: ' + str(error), file=sys.stderr)
        sys.exit(1)
