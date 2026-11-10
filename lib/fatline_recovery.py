#!/usr/bin/env python3
"""Select Agni's restart graph without changing running application binaries."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from compose_runtime import run, write_json
from compositions import require
from fatline_host_link import HostLink
from fatline_services import Services


def prepare(services, upgrade=False):
    link = services.link
    require(services.state and services.state['status'] == 'active', 'Activate the selected service profile first')
    source = services.selection('servicesRecovery')
    path = services.root / 'recovery.json'
    previous = json.loads(path.read_text()) if path.exists() else None
    require(not previous or previous['source'] == source or ((previous['status'] == 'installing' or upgrade) and
            previous['source']['revision'] in source.get('refreshFrom', [])),
            'Installed restart graph pins another revision; migrate explicitly')
    services.retain()
    root = '/nix/home/nixuser/.local/state/nix-xd/fatline-' + link.scope + '-recovery-' + source['revision']
    bundle = link.runtime.owner('nix', 'build', '--no-write-lock-file', '--print-out-paths', '--out-link', root,
        'github:dash-xd/agni/' + source['revision'] + '?dir=local/fatline#' + source['package'])
    require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+', bundle), 'Invalid recovery bundle')
    metadata = json.loads(link.runtime.owner('cat', bundle + '/metadata.json'))
    for key in ('schema', 'logmaRev', 'skymillRev', 'ratelimiterRev'):
        require(metadata[key] == services.state['metadata'][key], 'Restart adapter changes application component pins')
    require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/]+/bin/fatline-services-probe', metadata['probe']), 'Invalid recovery probe')
    script = link.runtime.owner('cat', bundle + '/recovery.sh') + '\n'
    record = {'source':source, 'root':root, 'bundle':bundle, 'probe':metadata['probe'],
        'sha256':hashlib.sha256(script.encode()).hexdigest(), 'status':'installing', 'boot':link.state['boot']}
    record['retiredRoots'] = list(previous.get('retiredRoots', [])) if previous else []
    if previous and previous['root'] != root:
        record['retiredRoots'].append({'root':previous['root'], 'bundle':previous['bundle']})
    write_json(path, record)
    invoke(services, record, 'install')
    record['status'] = 'installed'
    write_json(path, record)
    print('FATLINE_RESTART_PREPARE=passed application_binaries=unchanged roots=retained', flush=True)


def invoke(services, record, action):
    link = services.link
    script = '/var/mnt/nixstore/' + record['bundle'].removeprefix('/nix/store/') + '/recovery.sh'
    command = ['bash', script, action, link.scope, record['probe'], services.state['aclDigest']]
    body = 'set -Eeuo pipefail\n'
    body += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(link.state['boot']) + '\n'
    body += 'test "$(sha256sum ' + shlex.quote(script) + ' | cut -d " " -f 1)" = ' + shlex.quote(record['sha256']) + '\n'
    body += shlex.join(command) + '\n'
    try:
        output = run(link.command, link.env, True, body, timeout=900)
    except subprocess.SubprocessError:
        print('FATLINE_RESTART_FAILURE=collecting_read_only_diagnostics', flush=True)
        try:
            diagnose(services)
        except (OSError, subprocess.SubprocessError) as diagnostic_error:
            print('Restart diagnostics unavailable: ' + str(diagnostic_error), file=sys.stderr)
        raise
    print(output, end='', flush=True)
    expected = {'install':'FATLINE_RESTART_GRAPH=installed runtime=unchanged',
        'recover':'FATLINE_RESTART_RECOVERED=passed',
        'qualify':'FATLINE_REDIS_RESTART=passed bootstrap=revoked_on_disk_and_runtime boot=unchanged'}[action]
    require(expected in output.splitlines(), 'Missing Agni restart acknowledgement; roots retained')


def qualify(services):
    path = services.root / 'recovery.json'
    require(path.exists(), 'Run fatline-restart-prepare first')
    record = json.loads(path.read_text())
    require(record['status'] == 'installed' and record['source'] == services.selection('servicesRecovery'), 'Install the selected restart graph first')
    require(record['boot'] == services.link.state['boot'], 'Boot changed; explicit reboot reconciliation is required')
    services.retain()
    evidence = services.root / 'restart-qualification.json'
    write_json(evidence, {'result':'running', 'phase':'controlled-redis-restart'})
    passed = False
    try:
        invoke(services, record, 'qualify')
        passed = True
    finally:
        write_json(evidence, {'result':'passed' if passed else 'failed', 'phase':'controlled-redis-restart',
            'boot':services.link.state['boot'], 'adapter':record, 'persistence':'ephemeral',
            'rebootQualified':False, 'unexpectedCrashQualified':False, 'fullFatline':False})


def diagnose(services):
    link = services.link
    body = 'set -Eu\n' + 'scope=' + shlex.quote(link.scope) + '\n'
    body += r'''
base="$HOME/.local/state/nix-xd/fatline/$scope"
apps="$base/services"
runtime="$base/credentials/runtime"
printf 'DIAGNOSTIC_BOOT_ID=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
for role in redis nginx logma skymill; do
  echo "DIAGNOSTIC_UNIT=$scope-$role.service"
  systemctl --user show "$scope-$role.service" \
    -p LoadState -p ActiveState -p SubState -p Result -p InvocationID -p ExecMainCode -p ExecMainStatus
  podman inspect "$scope-$role" --format 'CONTAINER={{.Id}} RUNNING={{.State.Running}} EXIT={{.State.ExitCode}}' 2>&1 || true
done
for name in restart-before.ids restart-after.ids; do
  echo "DIAGNOSTIC_FILE=$name"
  if test -f "$apps/$name"; then cat "$apps/$name"; else echo absent; fi
done
if test -f "$runtime/ready"; then printf 'DIAGNOSTIC_BOOTSTRAP_INVOCATION='; cat "$runtime/ready"; else echo DIAGNOSTIC_BOOTSTRAP_READY=absent; fi
if test -f "$runtime/users.acl"; then
  stat -c 'DIAGNOSTIC_RUNTIME_ACL_MODE=%a' "$runtime/users.acl"
  if grep -Fxq 'user bootstrap reset off' "$runtime/users.acl"; then echo DIAGNOSTIC_BOOTSTRAP_FILE=disabled; else echo DIAGNOSTIC_BOOTSTRAP_FILE=not-disabled; fi
fi
journalctl --user --no-pager -b -n 100 -u "$scope-redis.service" -u "$scope-nginx.service" -u "$scope-logma.service" -u "$scope-skymill.service"
echo FATLINE_RESTART_DIAGNOSTIC=collected
'''
    output = run(link.command, link.env, True, body, timeout=60)
    print(output, end='', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare','qualify','diagnose','upgrade','recover'))
    action = parser.parse_args().action
    link = HostLink()
    with link.lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        services = Services(link)
        if action == 'upgrade':
            prepare(services, upgrade=True)
        elif action == 'recover':
            record = json.loads((services.root / 'recovery.json').read_text())
            require(record['status'] == 'installed' and record['source'] == services.selection('servicesRecovery'), 'Upgrade the selected restart helper first')
            require(record['boot'] == link.state['boot'], 'Boot changed; explicit reboot reconciliation required')
            services.retain()
            invoke(services, record, 'recover')
        else:
            {'prepare':prepare, 'qualify':qualify, 'diagnose':diagnose}[action](services)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Fatline restart error: ' + str(error), file=sys.stderr)
        sys.exit(1)
