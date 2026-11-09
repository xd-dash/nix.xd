#!/usr/bin/env python3
"""Run independent sandbox phases from a resolved flake composition."""
import argparse
import fcntl
import json
import re
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import uuid

from compositions import validate, require

REPO = Path(__file__).resolve().parents[1]


def run(argv, env, capture=False):
    try:
        result = subprocess.run(argv, env=env, text=True,
                                stdout=subprocess.PIPE if capture else None, check=True)
    except subprocess.CalledProcessError as error:
        if capture and error.stdout:
            print(error.stdout, end='', flush=True)
        raise
    return result.stdout if capture else ''


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class Runtime:
    def __init__(self, env):
        self.env = dict(env)
        self.scope = env.get('NIX_XD_SCOPE', 'nix-xd-arm')
        require(re.fullmatch(r'[a-z][a-z0-9-]{0,39}', self.scope), 'Invalid scope')
        self.machine = env.get('NIX_XD_MACHINE', 'coreos-arm64')
        self.flake = env.get('NIX_XD_WORKLOAD_FLAKE', '/workspaces/nix.xd')
        self.name = env.get('NIX_XD_COMPOSITION', 'shared-store-matrix')
        require(self.name == 'shared-store-matrix', 'Select a supported composition')
        require(env.get('NIX_XD_PROVIDER') == 'podman', 'Composition adapter requires Podman')
        self.primary = Path(env.get('COREOS_STATE_ROOT', str(REPO / '.state/coreos'))).resolve()
        self.root = REPO / '.state/compositions' / self.scope / self.name
        self.root.mkdir(parents=True, exist_ok=True)
        self.podman = ['podman'] + (['--connection', self.machine] if platform.system() == 'Darwin' else [])
        self.plan = None

    def owner(self, *args):
        return run(self.podman + ['exec', self.scope, *args], self.env, True).strip()

    def resolve(self, fresh=False):
        path = self.root / 'plan.json'
        revision = self.owner('cat', self.flake + '/.nix-xd-source-revision')
        require(revision == self.env.get('NIX_XD_WORKLOAD_REV'), 'Stage the selected committed revision first')
        if fresh:
            plan = validate(json.loads(self.owner('nix', 'run', '--no-write-lock-file', self.flake + '#composition-plan')))
            require(plan['system'] == self.env['NIX_XD_SYSTEM'], 'Composition architecture mismatch')
            plan['sourceRevision'] = revision
            # Preparation independently pins and validates each workload's immutable source.
            if path.exists() and json.loads(path.read_text()) != plan:
                raise ValueError('Existing composition plan differs; stop its readers before replacing plan.json')
            write_json(path, plan)
        else:
            require(path.exists(), 'Run composition-plan first')
            plan = validate(json.loads(path.read_text()))
            require(plan['sourceRevision'] == self.env.get('NIX_XD_WORKLOAD_REV'), 'Use the pinned revision or stop before preparing a new plan')
        for workload in plan['workloads'].values():
            require(workload['domain'] == 'common' and plan['domains']['common']['provisioning'] == 'existing-host-store',
                    'Additional store domains are declarative; provisioning is deferred')
        require(plan['system'] == self.env['NIX_XD_SYSTEM'], 'Composition architecture mismatch')
        self.plan = plan
        return plan

    def environment(self, name):
        binding = self.plan['workloads'][name]
        placement = self.plan['placements'][binding['placement']]
        env = dict(self.env, NIX_XD_WORKLOAD=name, NIX_XD_WORKLOAD_GENERATION='',
                   NIX_XD_WORKLOAD_PLACEMENT='host' if placement['kind'] == 'host' else 'guest',
                   COREOS_NIX_STORE_VOLUME=self.scope + '-store', COREOS_PROFILE='starwisp')
        # Qualification must not execute legacy probes from an unrelated caller.
        for key in ('COREOS_GUEST_PROBE_ROOTFS', 'COREOS_GUEST_NIX_EXECUTABLE',
                    'COREOS_GUEST_DYNAMIC_EXECUTABLE', 'COREOS_GUEST_OCI_ARCHIVE', 'COREOS_ARTIFACT_STATE'):
            env.pop(key, None)
        if placement['kind'] == 'coreos':
            env.update(COREOS_CONTAINER_NAME=placement['container'], COREOS_SSH_PORT=str(placement['sshPort']))
            if placement.get('reusePrimary'):
                env['COREOS_STATE_ROOT'] = str(self.primary)
            else:
                env['COREOS_STATE_ROOT'] = str(self.root / binding['placement'])
                env['COREOS_ARTIFACT_STATE'] = str(self.primary / 'starwisp')
        else:
            env['COREOS_STATE_ROOT'] = str(self.root)
        return env

    def workload(self, name, action, **extra):
        env = dict(self.environment(name), **extra)
        print('COMPOSITION_WORKLOAD name=' + name + ' action=' + action, flush=True)
        output = run(['bash', str(REPO / 'bin/nix-xd-workload'), action], env, True)
        print(output, end='', flush=True)
        return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)

    def control(self, name, action):
        return self.owner('nix', 'run', '--no-write-lock-file', self.flake + '#workload-control',
                          '--', action, '--name', name)

    def verify_bindings(self):
        for name, binding in self.plan['workloads'].items():
            state = json.loads(self.control(name, 'inspect'))
            generation = state['active'] or state['prepared']
            require(generation, 'Prepare every composition workload first: ' + name)
            manifest = state['generations'][generation]['manifest']
            declaration = manifest['declaration']
            expected = 'host' if self.plan['placements'][binding['placement']]['kind'] == 'host' else 'guest'
            require(manifest['source']['revision'] == self.plan['sourceRevision'] and
                    manifest['system'] == self.plan['system'], 'Workload source or architecture differs: ' + name)
            require(declaration.get('storeDomain') == binding['domain'] and
                    declaration.get('placement') == expected and
                    declaration['qualification']['mode'] == 'running', 'Workload binding differs: ' + name)

    def roots(self, name):
        return self.control(name, 'assert-retained')

    def probe(self, names, token, write=False):
        snapshots = {}
        for name in names:
            snapshots[name] = self.workload(name, 'isolate-write' if write else 'isolate-check',
                                             NIX_XD_ISOLATION_TOKEN=token)
            snapshots[name]['ISOLATION_ROOT_FINGERPRINT'] = self.roots(name)
        return snapshots

    def qualify(self):
        names = sorted(self.plan['workloads'])
        require(len(names) == 6, 'This qualification requires six readers')
        require(all(sum(w['placement'] == place for w in self.plan['workloads'].values()) == 2
                    for place in self.plan['placements']), 'Expected two readers per placement')
        token = uuid.uuid4().hex
        self.probe(names, token, write=True)
        before = self.probe(names, token)
        require(len({s['ISOLATION_CONTAINER_ID'] for s in before.values()}) == 6, 'Container identities overlap')
        for field in ('ISOLATION_NIX_PATH', 'ISOLATION_HELLO_PATH'):
            require(len({s[field] for s in before.values()}) == 1, 'Shared store paths differ')
        boots = {}
        for name, snapshot in before.items():
            place = self.plan['workloads'][name]['placement']
            boots.setdefault(place, set()).add(snapshot['ISOLATION_BOOT_ID'])
        require(len(boots) == 3 and all(len(v) == 1 for v in boots.values()) and
                len(set.union(*boots.values())) == 3, 'Expected host and two independently booted guests')
        require(len({(s['ISOLATION_BOOT_ID'], s['ISOLATION_PID_NAMESPACE']) for s in before.values()}) == 6,
                'Process namespaces overlap')
        for place in sorted(boots):
            victim = next(n for n in names if self.plan['workloads'][n]['placement'] == place)
            peers = [n for n in names if n != victim]
            self.workload(victim, 'recreate', NIX_XD_RECREATE_PAUSE='after-stop')
            require(self.roots(victim) == before[victim]['ISOLATION_ROOT_FINGERPRINT'],
                    'Victim roots changed during recreation')
            during = self.probe(peers, token)
            for peer in peers:
                require(all(during[peer][field] == before[peer][field] for field in
                            ('ISOLATION_CONTAINER_ID', 'ISOLATION_BOOT_ID', 'ISOLATION_ROOT_FINGERPRINT')),
                        'Peer identity or retained roots changed')
            self.workload(victim, 'recreate')
            after = self.probe([victim], token, write=True)[victim]
            require(after['ISOLATION_CONTAINER_ID'] != before[victim]['ISOLATION_CONTAINER_ID'], 'Victim was not replaced')
            require(after['ISOLATION_BOOT_ID'] == before[victim]['ISOLATION_BOOT_ID'], 'VM rebooted during recreation')
            require(after['ISOLATION_ROOT_FINGERPRINT'] == before[victim]['ISOLATION_ROOT_FINGERPRINT'],
                    'Replacement roots changed')
            before[victim] = after
            self.workload(victim, 'stop')
            stopped = json.loads(self.control(victim, 'summary'))
            require(not stopped['active'] and not stopped['rootsRetained'], 'Stopped reader roots not released')
            stopped_peers = self.probe(peers, token)
            for peer in peers:
                require(all(stopped_peers[peer][field] == before[peer][field] for field in
                            ('ISOLATION_CONTAINER_ID', 'ISOLATION_BOOT_ID', 'ISOLATION_ROOT_FINGERPRINT')),
                        'Stopping one reader changed a peer')
            self.workload(victim, 'prepare')
            self.workload(victim, 'activate')
            self.workload(victim, 'check')
            before[victim] = self.probe([victim], token, write=True)[victim]
        final = self.probe(names, token)
        write_json(self.root / 'qualification.json', {'result': 'passed', 'plan': self.plan, 'readers': final})
        print('COMPOSITION_QUALIFICATION=passed readers=6 placements=3')

    def execute(self, phase):
        self.resolve(phase == 'plan')
        names = sorted(self.plan['workloads'])
        if phase in ('prepare', 'start', 'qualify', 'stop'):
            write_json(self.root / 'qualification.json', {'result': 'unqualified', 'phase': phase})
        if phase in ('start', 'qualify'):
            self.verify_bindings()
        if phase == 'plan':
            print(json.dumps(self.plan, indent=2, sort_keys=True))
        elif phase in ('prepare', 'status', 'stop'):
            for name in names:
                if phase == 'stop':
                    state = json.loads(self.control(name, 'inspect'))
                    if not state['active']:
                        continue
                    entry = state['generations'][state['active']]
                    if entry['status'].startswith('recreating-'):
                        self.workload(name, 'recreate-abandon')
                        continue
                self.workload(name, phase)
            if phase == 'prepare':
                self.verify_bindings()
            if phase == 'stop':
                # VMs are deliberately left running: they may host other compositions.
                (self.root / 'plan.json').unlink()
        elif phase == 'start':
            require(platform.system() == 'Darwin' and self.env['NIX_XD_SYSTEM'] == 'aarch64-linux',
                    'Current VM adapter is ARM64 macOS; native x86 VM qualification is deferred')
            for place, declaration in self.plan['placements'].items():
                if declaration['kind'] == 'coreos':
                    name = next(n for n in names if self.plan['workloads'][n]['placement'] == place)
                    env = self.environment(name)
                    run(['bash', str(REPO / 'bin/nix-xd-coreos-podman'), 'start'], env)
                    run(['bash', str(REPO / 'bin/nix-xd-wisp-ssh')], env)
            for name in names:
                self.workload(name, 'activate')
                self.workload(name, 'check')
        elif phase == 'qualify':
            self.qualify()
        print('COMPOSITION_PHASE_RESULT=passed phase=' + phase)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('plan', 'prepare', 'start', 'status', 'qualify', 'stop'))
    args = parser.parse_args()
    require(sys.version_info >= (3, 9), 'Host qualification requires Python 3.9 or newer')
    runtime = Runtime(os.environ)
    with (runtime.root / 'composition.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime.execute(args.phase)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print('composition error: ' + str(error), file=sys.stderr)
        sys.exit(1)
