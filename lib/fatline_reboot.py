#!/usr/bin/env python3
"""Qualify one guest reboot without changing the owner store or the peer VM."""
from contextlib import ExitStack
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time

from compose_runtime import run, write_json
from compositions import require
from fatline_host_link import HostLink
from fatline_services import Services
from fatline_logmash import qualify as logmash_qualify
from fatline_recovery import diagnose

ROLES = ('redis','nginx','logma','skymill')
UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'


def observe(link):
    body = 'set -Eeuo pipefail\ncat /proc/sys/kernel/random/boot_id\n'
    for role in ROLES:
        name = shlex.quote(link.scope + '-' + role)
        body += 'systemctl --user is-active --quiet ' + name + '.service\n'
        body += 'podman inspect ' + name + " --format '{{.Id}}'\n"
    lines = run(link.command, link.env, True, body, timeout=60).strip().splitlines()
    require(len(lines) == 5 and re.fullmatch(UUID, lines[0]) and
            all(re.fullmatch(r'[a-f0-9]{64}', item) for item in lines[1:]), 'Invalid guest observation')
    return {'boot':lines[0], 'containers':dict(zip(ROLES, lines[1:]))}


def reboot_capability(link):
    body = r'''set -Eu
permission=$(busctl --system call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanReboot 2>/dev/null || true)
if [[ "$permission" == 's "yes"' ]]; then echo REBOOT_CAPABILITY=logind
else echo REBOOT_CAPABILITY=missing; fi
'''
    output = run(link.command, link.env, True, body, timeout=30).strip()
    require(output == 'REBOOT_CAPABILITY=logind',
        'Guest lacks noninteractive reboot authority. Rebootstrap with Agni\'s narrow Starwisp reboot policy; no sudo or forced power cycle was attempted.')
    return output.split('=',1)[1]


def helper(services, action, boot):
    link = services.link
    _, record = services.startup_record()
    script_name = record.get('script','recovery.sh')
    require(script_name in ('runtime.sh','recovery.sh'), 'Unsupported startup interface')
    script = '/var/mnt/nixstore/' + record['bundle'].removeprefix('/nix/store/') + '/' + script_name
    command = ['bash', script, action, link.scope, record['probe']]
    body = 'set -Eeuo pipefail\ntest "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(boot) + '\n'
    if action == 'boot-check':
        body += '/bin/bash "$HOME/.local/state/nix-xd/fatline/' + link.scope + '/services/boot-wait.sh" ' + shlex.quote(link.scope) + ' ' + shlex.quote(record['probe']) + '\n'
    body += 'test "$(sha256sum ' + shlex.quote(script) + ' | cut -d " " -f 1)" = ' + shlex.quote(record['sha256']) + '\n'
    output = run(link.command, link.env, True, body + shlex.join(command) + '\n', timeout=360)
    print(output, end='', flush=True)
    marker = {'boot-prepare':'FATLINE_REBOOT_PREPARED=passed',
        'boot-check':'FATLINE_REBOOT_BOOTSTRAP=passed store_before_services=true bootstrap=revoked'}[action]
    require(marker in output.splitlines(), 'Guest reboot acknowledgement missing; roots retained')


def validate_transition(before, after, peer_before, peer_after):
    require(before['boot'] != after['boot'], 'Guest boot ID did not change')
    require(all(before['containers'][role] != after['containers'][role] for role in ROLES), 'A service container did not change across reboot')
    require(peer_before == peer_after, 'VM2 boot or service containers changed')


def reconcile(link, services, transaction, transaction_path):
    old, new = transaction['before']['boot'], transaction['after']['boot']
    require(re.fullmatch(UUID, new) and old != new, 'Invalid boot transition')
    # Resume safely if only one of the two atomic record writes completed.
    require(link.state['boot'] in (old,new), 'Transport record belongs to another boot')
    path, record = services.startup_record()
    require(record['boot'] in (old,new) and record['source'] == transaction['adapterSource'], 'Restart helper binding changed')
    link.state['boot'] = new
    link.state['lastReboot'] = {'transaction':transaction['id'], 'from':old, 'to':new}
    write_json(link.state_path, link.state)
    record['boot'] = new
    write_json(path, record)
    transaction['phase'] = 'reconciled'
    write_json(transaction_path, transaction)


def wait_new_boot(link, old, timeout=900):
    deadline = time.monotonic() + timeout
    last = 'not yet connected'
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(link.command, env=link.env, input='cat /proc/sys/kernel/random/boot_id\n',
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        except subprocess.TimeoutExpired:
            print('FATLINE_REBOOT_WAIT=SSH_timeout', flush=True)
            continue
        value = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(UUID, value) and value != old:
            print('FATLINE_REBOOT_SSH=ready boot=' + value, flush=True)
            return value
        if 'REMOTE HOST IDENTIFICATION HAS CHANGED' in result.stderr or 'Host key verification failed' in result.stderr:
            raise ValueError('Trusted SSH host identity changed; refusing reconciliation')
        last = 'old boot still running' if result.returncode == 0 else 'SSH not ready'
        print('FATLINE_REBOOT_WAIT=' + last, flush=True)
        time.sleep(5)
    raise ValueError('Guest did not return with a new boot ID within %ss (%s)' % (timeout,last))


def run_gate(link, peer, resume=False):
    services, peer_services = Services(link), Services(peer)
    require(services.state and services.state['status'] == 'active', 'VM1 services must be active in owner intent')
    require(peer_services.state and peer_services.state['status'] == 'active', 'VM2 services must be active')
    recovery_path, record = services.startup_record()
    require(record is not None, 'Apply the selected startup profile before reboot qualification')
    desired = record['source'] if record.get('script') == 'runtime.sh' else services.selection('servicesRecovery')
    require(record['status'] == 'installed' and record['source'] == desired, 'Apply the selected startup profile before reboot qualification')
    path = services.root / 'reboot-transaction.json'
    saved = json.loads(path.read_text()) if path.exists() else None
    pending = saved and saved['phase'] != 'passed'
    require(not resume or pending, 'No pending reboot transaction to resume')
    services.retain()
    peer_services.retain()
    if pending:
        transaction = saved
        require(transaction['adapterSource'] == record['source'], 'Pending transaction pins another adapter')
        print('FATLINE_REBOOT_RESUME=' + transaction['phase'], flush=True)
    else:
        before, peer_before = observe(link), observe(peer)
        require(before['boot'] == link.state['boot'] and peer_before['boot'] == peer.state['boot'], 'Reconcile existing boot changes before a new reboot')
        require(before['boot'] != peer_before['boot'], 'VM profiles resolve to the same boot')
        capability = reboot_capability(link)
        helper(services, 'boot-prepare', before['boot'])
        transaction = {'id':secrets.token_hex(16), 'phase':'prepared','before':before,'peerBefore':peer_before,
            'adapterSource':record['source'], 'capability':capability}
        write_json(path, transaction)
    evidence = services.root / 'reboot-qualification.json'
    write_json(evidence, {'result':'running','transaction':transaction['id'],'phase':transaction['phase']})
    try:
        if transaction['phase'] == 'prepared':
            # Persist intent before requesting reboot: resume never issues a duplicate request.
            for old_evidence in (services.root / 'qualification.json', services.root / 'restart-qualification.json',
                                 link.root / 'qualification.json', link.root / 'resource-logmash-qualification.json', link.root / 'logmash-qualification.json'):
                write_json(old_evidence, {'result':'unqualified','phase':'reboot-requested','transaction':transaction['id']})
            transaction['phase'] = 'requested'
            write_json(path, transaction)
            require(transaction['capability'] == 'logind', 'Reboot must use the declaratively provisioned logind capability')
            command = '/usr/bin/systemctl --no-ask-password reboot'
            result = subprocess.run(link.command, env=link.env, text=True,
                input='set -Eeuo pipefail\ntest "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(transaction['before']['boot']) + '\n' + command + '\n',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            require(result.returncode in (0,255), 'Guest rejected reboot request: ' + result.stderr.strip())
            print('FATLINE_REBOOT_REQUEST=sent', flush=True)
        if transaction['phase'] == 'requested':
            boot = wait_new_boot(link, transaction['before']['boot'])
            # No controller start/recover calls here: startup must be autonomous.
            helper(services, 'boot-check', boot)
            after, peer_after = observe(link), observe(peer)
            validate_transition(transaction['before'], after, transaction['peerBefore'], peer_after)
            transaction.update(after=after, phase='observed')
            write_json(path, transaction)
        if transaction['phase'] == 'observed':
            reconcile(link, services, transaction, path)
        require(transaction['phase'] == 'reconciled', 'Invalid pending reboot phase')
        require(observe(link)['boot'] == transaction['after']['boot'], 'VM1 rebooted again during qualification')
        services.execute('qualify')
        logmash_qualify(link, resource=True)
        require(observe(link) == transaction['after'], 'VM1 service containers changed during post-reboot checks')
        require(observe(peer) == transaction['peerBefore'], 'VM2 changed during post-reboot application checks')
        services.retain()
        peer_services.retain()
        transaction['phase'] = 'passed'
        write_json(path, transaction)
        write_json(evidence, {'result':'passed','transaction':transaction, 'rootsRetained':True,
            'persistence':'ephemeral','unexpectedCrashQualified':False,'fullFatline':False})
        print('FATLINE_REBOOT_RESULT=passed autonomous_startup=true peer_vm=unchanged', flush=True)
    except (ValueError, OSError, subprocess.SubprocessError):
        write_json(evidence, {'result':'failed','transaction':transaction,'rootsRetained':True,'fullFatline':False})
        try: diagnose(services)
        except (OSError,subprocess.SubprocessError) as error: print('Reboot diagnostics unavailable: ' + str(error), file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan','run','resume'))
    action = parser.parse_args().action
    require(os.environ.get('NIX_XD_FATLINE_PROFILE','vm1') == 'vm1', 'This gate reboots VM1 only')
    with ExitStack() as locks:
        original = dict(os.environ)
        links = []
        try:
            for profile in ('vm1','vm2'):
                os.environ.update(NIX_XD_FATLINE_PROFILE=profile, NIX_XD_FATLINE_SCOPE='fatline-arm-' + profile)
                link = HostLink()
                lock = locks.enter_context(link.lock_path.open('a'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                links.append(link)
        finally:
            os.environ.clear(); os.environ.update(original)
        if action == 'plan':
            capability = reboot_capability(links[0])
            before, peer = observe(links[0]), observe(links[1])
            require(before['boot'] != peer['boot'], 'Profiles refer to the same guest')
            print('FATLINE_REBOOT_PLAN=passed capability=' + capability + ' target=vm1 peer=vm2 persistence=ephemeral', flush=True)
        else: run_gate(*links, resume=action == 'resume')


if __name__ == '__main__':
    try: main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        print('Fatline reboot error: ' + str(error), file=sys.stderr)
        sys.exit(1)
