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


def prepare(services):
    link = services.link
    require(services.state and services.state['status'] == 'active', 'Activate the selected service profile first')
    source = services.selection('servicesRecovery')
    path = services.root / 'recovery.json'
    previous = json.loads(path.read_text()) if path.exists() else None
    require(not previous or previous['source'] == source or (previous['status'] == 'installing' and
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
    output = run(link.command, link.env, True, body, timeout=900)
    print(output, end='', flush=True)
    expected = 'FATLINE_RESTART_GRAPH=installed runtime=unchanged' if action == 'install' else 'FATLINE_REDIS_RESTART=passed bootstrap=revoked_on_disk_and_runtime boot=unchanged'
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare','qualify'))
    action = parser.parse_args().action
    link = HostLink()
    with (link.root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        services = Services(link)
        (prepare if action == 'prepare' else qualify)(services)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Fatline restart error: ' + str(error), file=sys.stderr)
        sys.exit(1)
