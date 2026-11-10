#!/usr/bin/env python3
"""Qualify Smoke Logmash over the separately qualified Wisp SSH transport."""
import argparse
import secrets
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from compose_runtime import write_json
from compositions import require
from fatline_host_link import HostLink, REPO


def wait_log(process, path, expected, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if expected in path.read_text().splitlines():
            return
        require(process.poll() is None, 'Process exited before acknowledgement; see ' + str(path))
        time.sleep(0.2)
    raise ValueError('Acknowledgement timed out; see ' + str(path))


def subscriber_environment(base, password, source='us:vm1'):
    # Keep credentials process-scoped; neither command arguments nor logs contain them.
    prefix = 'LOGMASH_REDIS_' + source.upper().replace(':', '_')
    return dict(base, **{prefix + '_USERNAME':'subscriber', prefix + '_PASSWORD':password})


def qualify(link, resource=False):
    link.retain()
    source = link.config.get('logicalSource', 'us:' + getattr(link, 'profile', 'vm1'))
    root = link.root
    result = root / ('resource-logmash-qualification.json' if resource else 'logmash-qualification.json')
    write_json(result, {'result':'running', 'gate':'smoke-logmash-wisp'})
    binary = REPO / '.state/wisp-go/smoke'
    revision = os.environ['WISP_SMOKE_REV']
    require(binary.is_file() and (binary.parent / 'revision').read_text().strip() == revision,
            'Build the selected Smoke composition first')
    link.guest('status')
    link.guest('check')
    config = json.loads((root / 'credentials/subscriber.json').read_text())
    if resource:
        config['payload'] = secrets.token_hex(24)
    password = Path(config['passwordFile']).read_text().strip()
    require(config['username'] == 'subscriber' and len(password) >= 32, 'Invalid subscriber credential')
    channel = link.scope + ':qualification'
    require(config['channel'] == channel, 'Channel differs from scoped declaration')
    socket_path = root / 'logmash.sock'
    require(not socket_path.exists() and not socket_path.is_symlink(), 'Existing socket path is not owned by this run')
    transport_log = root / 'logmash-wisp.log'
    subscriber_log = root / 'logmash-subscriber.log'
    known_hosts = Path(link.env.get('COREOS_STATE_ROOT', str(link.runtime.primary))) / 'starwisp/known_hosts'
    tunnel_command = [str(binary), 'wisp', 'forward', '--address',
        '127.0.0.1:' + str(link.config['placement']['sshPort']), '--user',
        os.environ.get('COREOS_GUEST_USER', 'wisp'), '--identity', os.environ['COREOS_SSH_KEY'],
        '--known-hosts', str(known_hosts), '--listen', str(socket_path),
        '--target-network', 'tcp', '--target', '127.0.0.1:16379', '--timeout', '10m']
    native = [str(binary), 'logmash', '--redis-socket', str(socket_path), '--auth-provider', 'acl-env']
    env = subscriber_environment(link.env, password, source)
    tunnel = subscriber = None
    passed = False
    resource_binding = None
    try:
        with transport_log.open('w') as transport_output, subscriber_log.open('w') as output:
            tunnel = subprocess.Popen(tunnel_command, env=link.env, stdin=subprocess.DEVNULL,
                                      stdout=transport_output, stderr=subprocess.STDOUT)
            wait_log(tunnel, transport_log, 'WISP_FORWARD_READY=true', 30)
            # Exercise auth and channel restrictions through the actual Smoke command.
            for name, selector, credentials, expected in (
                ('wrong-password', channel, subscriber_environment(link.env, 'invalid-qualification-password', source), 'WRONGPASS'),
                ('foreign-channel', 'foreign:qualification', env, 'NOPERM')):
                denied = subprocess.run(native + [source + ':' + selector], env=credentials,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=60)
                (root / ('logmash-' + name + '.log')).write_text(denied.stdout)
                require(denied.returncode != 0 and expected in denied.stdout,
                        'Expected denial missing: ' + name)
                print('SMOKE_LOGMASH_DENIAL=' + name, flush=True)
            subscriber = subprocess.Popen(native + [source + ':' + channel], env=env,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
            wait_log(subscriber, subscriber_log, 'logmash: ready source=' + source, 60)
            print('SMOKE_LOGMASH_SUBSCRIBER_READY=true', flush=True)
            if resource:
                from fatline_services import Services
                request = root / ('resource-' + secrets.token_hex(12) + '.json')
                write_json(request, {'Channel':channel,'PublisherID':'nix-xd-dispatch-' + secrets.token_hex(12),'Payload':config['payload']})
                try:
                    services = Services(link)
                    resource_binding = {'runtimeSource':services.state['source'], 'qualificationProbe':services.state.get('qualificationProbe'), 'configurationAdapter':services.state.get('configurationAdapter')}
                    services.dispatch(request)
                finally:
                    request.unlink(missing_ok=True)
            else:
                link.guest('publish')
            wait_log(subscriber, subscriber_log, source + ':' + channel + '\t' + config['payload'], 60)
            print('SMOKE_LOGMASH_MESSAGE=passed', flush=True)
            subscriber.send_signal(signal.SIGTERM)
            require(subscriber.wait(timeout=15) == 0, 'Logmash did not cancel cleanly')
            print('SMOKE_LOGMASH_CANCELLATION=passed', flush=True)
            tunnel.send_signal(signal.SIGTERM)
            require(tunnel.wait(timeout=15) == 0, 'Wisp did not stop cleanly')
            require(not socket_path.exists(), 'Wisp socket remained after shutdown')
            print('SMOKE_LOGMASH_SOCKET_CLEANUP=passed', flush=True)
            link.guest('status')
            link.retain()
            passed = True
    finally:
        for process in (subscriber, tunnel):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        write_json(result, {'result':'passed' if passed else 'failed', 'gate':'smoke-logmash-wisp',
            'resourceBinding':resource_binding, 'resourceBacked':resource, 'smokeRev':revision, 'agniRev':link.state['agniRev'], 'boot':link.state['boot'],
            'aclDigest':link.state['aclDigest'], 'guestAdapter':link.state.get('guestAdapter'), 'fullFatline':False})
    print('SMOKE_LOGMA_RESOURCE_DISPATCH_RESULT=passed full_fatline=false' if resource else 'SMOKE_LOGMASH_WISP_RESULT=passed full_fatline=false')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource", action="store_true")
    args = parser.parse_args()
    link = HostLink()
    with (link.root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        qualify(link, resource=args.resource)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Smoke Logmash qualification error: ' + str(error), file=sys.stderr)
        sys.exit(1)
