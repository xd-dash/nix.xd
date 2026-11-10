#!/usr/bin/env python3
"""Bounded, host-brokered subscription between independently scoped guests."""
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import subprocess
import sys
import time

from compose_runtime import run, write_json
from compositions import require
from fatline_host_link import HostLink, REPO
from fatline_logmash import wait_log
from fatline_services import Services


def dispatch_request(scope, token, payload):
    return {'Channel':scope + ':qualification', 'PublisherID':'nix-xd-dispatch-' + token, 'Payload':payload}


def snapshot(link):
    script = 'set -Eeuo pipefail\n'
    script += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(link.state['boot']) + '\n'
    for role in ('redis', 'nginx', 'logma', 'skymill'):
        name = shlex.quote(link.scope + '-' + role)
        script += 'test "$(podman inspect ' + name + ' --format \'{{.State.Running}}\')" = true\n'
        script += 'podman inspect ' + name + ' --format \'{{.Id}}\'\n'
    return run(link.command, link.env, True, script, timeout=30).strip()


def tunnel_command(link, binary, path):
    return [str(binary), 'wisp', 'forward', '--address', '127.0.0.1:' + str(link.config['placement']['sshPort']),
        '--user', link.env.get('COREOS_GUEST_USER', 'wisp'), '--identity', link.env['COREOS_SSH_KEY'],
        '--known-hosts', str(Path(link.env['COREOS_STATE_ROOT']) / 'starwisp/known_hosts'),
        '--listen', str(path), '--target-network', 'tcp', '--target', '127.0.0.1:16379', '--timeout', '5m']


def direction(source, target, binary, guest_binary, root):
    token = secrets.token_hex(12)
    name = 'nix-xd-cross-' + token
    # A short private Mac path avoids sockaddr_un's platform-dependent length limit.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='nxc-') as directory:
        local_socket = Path(directory) / 'r.sock'
        remote = str(Path(source.state['incoming']).parent / name)
        password = (target.root / 'credentials/subscriber').read_text().strip()
        require(re.fullmatch(r'[A-Za-z0-9_-]{32,}', password), 'Invalid subscriber credential encoding')
        create = 'umask 077\nmkdir ' + shlex.quote(remote) + '\nprintf %s ' + shlex.quote(password) + ' > ' + shlex.quote(remote + '/subscriber') + '\n'
        run(source.command, source.env, True, 'set -Eeuo pipefail\n' + create, timeout=30)
        processes = []
        passed = False
        try:
            with (root / (name + '-wisp.log')).open('w') as wisp_log, (root / (name + '-reverse.log')).open('w') as reverse_log, (root / (name + '-subscriber.log')).open('w') as subscriber_log:
                tunnel = subprocess.Popen(tunnel_command(target, binary, local_socket), env=target.env,
                    stdin=subprocess.DEVNULL, stdout=wisp_log, stderr=subprocess.STDOUT)
                processes.append(tunnel)
                wait_log(tunnel, Path(wisp_log.name), 'WISP_FORWARD_READY=true', 30)
                reverse_command = source.command[:-2] + [
                    '-o', 'ExitOnForwardFailure=yes', '-o', 'StreamLocalBindMask=0177',
                    '-R', remote + '/redis.sock:' + str(local_socket), '-N', source.command[-2]]
                reverse = subprocess.Popen(reverse_command, env=source.env, stdin=subprocess.DEVNULL,
                    stdout=reverse_log, stderr=subprocess.STDOUT)
                processes.append(reverse)
                deadline = time.monotonic() + 30
                while True:
                    require(reverse.poll() is None, 'Reverse SSH listener failed; see ' + reverse_log.name)
                    ready = run(source.command, source.env, True,
                        'if test -S ' + shlex.quote(remote + '/redis.sock') + '; then stat -c %a ' + shlex.quote(remote + '/redis.sock') + '; fi\n', timeout=15).strip()
                    if ready:
                        require(ready == '600', 'Reverse socket permissions differ from 0600')
                        break
                    require(time.monotonic() < deadline, 'Reverse socket readiness timed out')
                    time.sleep(0.2)
                logical = target.config.get('logicalSource', 'us:' + target.profile)
                prefix = 'LOGMASH_REDIS_' + logical.upper().replace(':', '_')
                # Resolve the authenticated guest's home instead of inferring it from a path shape.
                guest_home = run(source.command, source.env, True, 'printf %s "$HOME"\n', timeout=15).strip()
                rootfs = guest_home + '/.local/state/nix-xd/fatline/' + source.scope + '/services/rootfs'
                wrapper = 'export ' + prefix + '_PASSWORD="$(/bin/busybox cat /run/redis/subscriber)"; exec "$@"'
                command = ['systemd-run', '--user', '--wait', '--pipe', '--collect', '--unit=' + name,
                    '--property=RuntimeMaxSec=180s', '--property=TimeoutStopSec=20s',
                    'podman', 'run', '--rm', '--name', name, '--network', 'none',
                    '--userns', 'keep-id:uid=1000,gid=1000', '--user', '1000:1000',
                    '--read-only', '--read-only-tmpfs=false', '--security-opt', 'label=disable',
                    '--cap-drop', 'all', '--security-opt', 'no-new-privileges',
                    '--mount', 'type=bind,src=/var/mnt/nixstore,dst=/nix/store,ro',
                    '--mount', 'type=bind,src=' + remote + ',dst=/run/redis,ro',
                    '--env', prefix + '_USERNAME=subscriber', '--rootfs', rootfs,
                    '/bin/sh', '-ec', wrapper, 'subscriber', guest_binary, 'logmash',
                    '--redis-socket', '/run/redis/redis.sock', '--auth-provider', 'acl-env',
                    logical + ':' + target.scope + ':qualification']
                subscriber = subprocess.Popen(source.command, env=source.env, stdin=subprocess.PIPE,
                    stdout=subscriber_log, stderr=subprocess.STDOUT, text=True)
                processes.append(subscriber)
                subscriber.stdin.write('set -Eeuo pipefail\n' + shlex.join(command) + '\n')
                subscriber.stdin.close()
                wait_log(subscriber, Path(subscriber_log.name), 'logmash: ready source=' + logical, 45)
                payload = secrets.token_hex(24)
                request = root / (name + '.json')
                write_json(request, dispatch_request(target.scope, token, payload))
                try: Services(target).dispatch(request)
                finally: request.unlink(missing_ok=True)
                wait_log(subscriber, Path(subscriber_log.name), logical + ':' + target.scope + ':qualification\t' + payload, 45)
                run(source.command, source.env, True, 'podman stop --time 15 ' + shlex.quote(name) + '\n', timeout=30)
                require(subscriber.wait(timeout=30) == 0, 'Guest Logmash did not cancel cleanly')
                run(source.command, source.env, True, '! podman container exists ' + shlex.quote(name) + '\n', timeout=15)
                passed = True
        finally:
            # Stop our bounded transient unit before removing its credential/socket directory.
            cleanup = 'systemctl --user stop ' + shlex.quote(name + '.service') + ' >/dev/null 2>&1 || true\n'
            cleanup += 'if podman container exists ' + shlex.quote(name) + '; then podman rm -f ' + shlex.quote(name) + '; fi\n'
            try: run(source.command, source.env, True, cleanup, timeout=45)
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                run(source.command, source.env, True, 'rm -f -- ' + shlex.quote(remote + '/subscriber') + ' ' + shlex.quote(remote + '/redis.sock') + '\nrmdir -- ' + shlex.quote(remote) + '\n', timeout=30)
        require(passed and not local_socket.exists(), 'Cross-VM forwarding cleanup failed')
    print('FATLINE_CROSS_DIRECTION=passed source=' + source.profile + ' target=' + target.profile, flush=True)


def main():
    links = []
    with ExitStack() as locks:
        original = dict(os.environ)
        try:
            for profile in ('vm1', 'vm2'):
                os.environ.update(NIX_XD_FATLINE_PROFILE=profile, NIX_XD_FATLINE_SCOPE='fatline-arm-' + profile)
                link = HostLink()
                lock = locks.enter_context((link.root / 'controller.lock').open('a'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                link.retain()
                services = Services(link)
                require(services.state and services.state['status'] == 'active', 'Activate both service profiles first')
                services.retain()
                links.append(link)
        finally:
            os.environ.clear()
            os.environ.update(original)
        require(links[0].state['boot'] != links[1].state['boot'], 'Profiles resolve to the same VM boot')
        for credential in ('publisher', 'subscriber'):
            require((links[0].root / 'credentials' / credential).read_bytes() !=
                    (links[1].root / 'credentials' / credential).read_bytes(), 'Profiles share Redis credentials')
        root = REPO / '.state/fatline/cross'
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        result = root / 'qualification.json'
        write_json(result, {'result':'running', 'transport':'host-brokered-ssh'})
        state = REPO / '.state/wisp-go'
        revision = os.environ['WISP_SMOKE_REV']
        require((state / 'revision').read_text().strip() == revision and
                (state / 'linux-revision').read_text().strip() == revision, 'Build matching native and Linux Smoke binaries first')
        guest_binary = (state / 'linux-path').read_text().strip()
        require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-smoke-linux-(arm64|amd64)', guest_binary), 'Invalid retained Linux binary')
        before = [snapshot(link) for link in links]
        passed = False
        try:
            direction(links[0], links[1], state / 'smoke', guest_binary, root)
            direction(links[1], links[0], state / 'smoke', guest_binary, root)
            require(before == [snapshot(link) for link in links], 'A Fatline service container changed during the gate')
            for link in links: Services(link).retain()
            passed = True
        finally:
            write_json(result, {'result':'passed' if passed else 'failed', 'transport':'host-brokered-ssh',
                'smokeRev':revision, 'boots':{link.profile:link.state['boot'] for link in links}, 'fullFatline':False})
        print('FATLINE_CROSS_RESULT=passed independent_credentials=true peers_unchanged=true', flush=True)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Fatline cross-VM error: ' + str(error), file=sys.stderr)
        sys.exit(1)
