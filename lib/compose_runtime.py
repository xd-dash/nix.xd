#!/usr/bin/env python3
"""Run independent sandbox phases from a resolved flake composition."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import re
import shlex
import shutil
import signal
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import uuid

from compositions import validate, require

REPO = Path(__file__).resolve().parents[1]


def run(argv, env, capture=False, input_text=None, timeout=None):
    try:
        result = subprocess.run(argv, env=env, text=True,
                                stdout=subprocess.PIPE if capture else None, check=True,
                                input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if error.stdout:
            output = error.stdout.decode(errors='replace') if isinstance(error.stdout, bytes) else error.stdout
            print(output, end='', flush=True)
        raise
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
        self.binding_overrides = {}
        self.probe_round = 0

    def owner(self, *args):
        return run(self.podman + ['exec', self.scope, *args], self.env, True).strip()

    def resolve(self, fresh=False, stopping=False):
        path = self.root / 'plan.json'
        revision = self.owner('cat', self.flake + '/.nix-xd-source-revision')
        require(re.fullmatch(r'[a-f0-9]{40}', revision), 'Invalid staged source revision')
        if not stopping:
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
            if not stopping:
                require(plan['sourceRevision'] == self.env.get('NIX_XD_WORKLOAD_REV'), 'Use the pinned revision or stop before preparing a new plan')
        for workload in plan['workloads'].values():
            require(workload['domain'] == 'common' and plan['domains']['common']['provisioning'] == 'existing-host-store',
                    'Additional store domains are declarative; provisioning is deferred')
        require(plan['system'] == self.env['NIX_XD_SYSTEM'], 'Composition architecture mismatch')
        require(set(plan['workloads']) == {'shared-' + place + '-' + replica
                    for place in ('host', 'vm1', 'vm2') for replica in ('a', 'b')}, 'Unexpected sandbox reader identities')
        self.plan = plan
        self.pin_controller(revision)
        return plan

    def pin_controller(self, revision):
        started = time.monotonic()
        print('COMPOSITION_CONTROLLER resolving=true', flush=True)
        directory = '/nix/home/nixuser/.local/state/nix-xd'
        self.owner('mkdir', '-p', directory)
        output = self.owner('nix', 'build', '--no-write-lock-file', '--print-out-paths',
                            '--out-link', directory + '/controller-' + revision,
                            self.flake + '#workload-control')
        require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+', output), 'Invalid controller output')
        self.controller = output + '/bin/nix-xd-workload-control'
        self.env['NIX_XD_WORKLOAD_CONTROLLER'] = self.controller
        print('COMPOSITION_CONTROLLER resolved=true elapsed_sec=%.2f' % (time.monotonic() - started), flush=True)

    def batch(self, requests):
        output = run(self.podman + ['exec', '-i', self.scope, self.controller, 'batch'],
                     self.env, True, json.dumps(requests), timeout=120)
        return json.loads(output)

    def placement(self, name):
        declaration = self.plan['placements'][name]
        if declaration['kind'] != 'coreos':
            return declaration, None
        path = REPO / '.state/vm-bindings' / self.scope / (name + '.json')
        binding = getattr(self, 'binding_overrides', {}).get(name)
        if binding is None and path.exists():
            binding = json.loads(path.read_text())
        if binding is None:
            return declaration, None
        require(binding.get('schema') == 1 and binding.get('logical') == name and
                binding.get('baseContainer') == declaration['container'], 'VM binding differs from declared placement')
        require(re.fullmatch(r'[a-z][a-z0-9-]{0,63}', binding['container']) and
                type(binding['sshPort']) is int and 1024 <= binding['sshPort'] <= 65535 and
                Path(binding['stateRoot']).is_absolute(), 'Invalid physical VM binding')
        return dict(declaration, container=binding['container'], sshPort=binding['sshPort']), binding

    def environment(self, name):
        binding = self.plan['workloads'][name]
        placement, physical = self.placement(binding['placement'])
        env = dict(self.env, NIX_XD_WORKLOAD=name, NIX_XD_WORKLOAD_GENERATION='',
                   NIX_XD_WORKLOAD_PLACEMENT='host' if placement['kind'] == 'host' else 'guest',
                   COREOS_NIX_STORE_VOLUME=self.env.get('NIX_XD_STORE_VOLUME', self.scope + '-store'), COREOS_PROFILE='starwisp')
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
            if physical:
                env['COREOS_STATE_ROOT'] = physical['stateRoot']
                env.pop('COREOS_ARTIFACT_STATE', None)
        else:
            env['COREOS_STATE_ROOT'] = str(self.root)
        return env

    def workload(self, name, action, **extra):
        env = dict(self.environment(name), **extra)
        print('COMPOSITION_WORKLOAD name=' + name + ' action=' + action, flush=True)
        started = time.monotonic()
        output = run(['bash', str(REPO / 'bin/nix-xd-workload'), action], env, True)
        print(output, end='', flush=True)
        print('COMPOSITION_WORKLOAD_DONE name=%s action=%s elapsed_sec=%.2f' %
              (name, action, time.monotonic() - started), flush=True)
        return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)

    def control(self, name, action):
        return self.owner(self.controller, action, '--name', name)

    def verify_bindings(self):
        states = self.batch([{'name': name, 'action': 'inspect'} for name in self.plan['workloads']])
        for name, binding in self.plan['workloads'].items():
            state = states[name]
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

    def transport_command(self, place, name):
        env = self.environment(name)
        placement, _ = self.placement(place)
        if placement['kind'] == 'host':
            command = (['podman', 'machine', 'ssh', self.machine, 'bash -se']
                       if platform.system() == 'Darwin' else ['bash', '-se'])
        else:
            state = Path(env['COREOS_STATE_ROOT']) / 'starwisp'
            require('port=' + str(placement['sshPort']) in (state / 'manifest.txt').read_text().splitlines(),
                    'VM port differs from boot manifest')
            require('shared_nix_volume=' + self.env.get('NIX_XD_STORE_VOLUME', self.scope + '-store') in (state / 'build.txt').read_text().splitlines(),
                    'VM store binding differs')
            command = ['ssh', '-T', '-i', env['COREOS_SSH_KEY'], '-p', str(placement['sshPort']),
                       '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=10',
                       '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(state / 'known_hosts'),
                       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4',
                       env.get('COREOS_GUEST_USER', 'wisp') + '@127.0.0.1', 'bash -se']
        return command, env

    def placement_probe(self, place, names, bundle):
        env = self.environment(names[0])
        started = time.monotonic()
        scripts = []
        for name in names:
            scripts.append("printf 'COMPOSITION_READER_BEGIN=%s\\n' " + shlex.quote(name))
            # Each subshell closes its lifecycle lock before the next reader.
            scripts.append('(\n' + bundle[name]['script'] + '\n)')
            scripts.append("printf 'COMPOSITION_READER_END=%s\\n' " + shlex.quote(name))
        payload = '\n'.join(scripts) + '\n'
        command, env = self.transport_command(place, names[0])
        output = run(command, env, True, payload, timeout=300)
        evidence = self.root / ('probe-%03d-%s.log' % (getattr(self, 'probe_round', 0), place))
        evidence.write_text(output)
        snapshots, current, fields = {}, None, {}
        for line in output.splitlines():
            if line.startswith('COMPOSITION_READER_BEGIN='):
                require(current is None, 'Overlapping reader output')
                current, fields = line.split('=', 1)[1], {}
            elif line.startswith('COMPOSITION_READER_END='):
                require(current in names and line.split('=', 1)[1] == current, 'Unmatched reader output')
                require(fields.get('WORKLOAD_ISOLATION_OK') == bundle[current]['generation'], 'Reader acknowledgement missing')
                for field in ('ISOLATION_CONTAINER_ID', 'ISOLATION_BOOT_ID', 'ISOLATION_PID_NAMESPACE',
                              'ISOLATION_NIX_PATH', 'ISOLATION_HELLO_PATH'):
                    require(fields.get(field), 'Missing reader evidence: ' + field)
                require(fields.get('ISOLATION_STATE') == 'private' and fields.get('ISOLATION_STORE') == 'read-only',
                        'Reader isolation failed')
                fields['ISOLATION_ROOT_FINGERPRINT'] = bundle[current]['fingerprint']
                snapshots[current] = fields
                current = None
            elif current is not None and '=' in line:
                key, value = line.split('=', 1)
                fields[key] = value
        require(current is None and set(snapshots) == set(names), 'Incomplete placement probe')
        return snapshots, time.monotonic() - started

    def probe(self, names, token, write=False):
        started = time.monotonic()
        self.probe_round = getattr(self, 'probe_round', 0) + 1
        mode = 'write' if write else 'check'
        print('COMPOSITION_PROBE_START mode=%s readers=%s' % (mode, len(names)), flush=True)
        bundle = self.batch([{'name': name, 'action': 'isolation', 'token': token, 'mode': mode} for name in names])
        groups = {}
        for name in names:
            groups.setdefault(self.plan['workloads'][name]['placement'], []).append(name)
        snapshots = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            pending = {executor.submit(self.placement_probe, place, readers, bundle): place
                       for place, readers in groups.items()}
            for future in as_completed(pending):
                place = pending[future]
                results, elapsed = future.result()
                snapshots.update(results)
                for name, fields in sorted(results.items()):
                    print('COMPOSITION_READER name=%s container=%s boot=%s roots=%s' %
                          (name, fields['ISOLATION_CONTAINER_ID'], fields['ISOLATION_BOOT_ID'],
                           fields['ISOLATION_ROOT_FINGERPRINT']), flush=True)
                print('COMPOSITION_PROBE placement=%s mode=%s readers=%s elapsed_sec=%.2f' %
                      (place, mode, len(results), elapsed), flush=True)
        retained = self.batch([{'name': name, 'action': 'roots'} for name in names])
        for name in names:
            require(retained[name]['fingerprint'] == bundle[name]['fingerprint'] and
                    retained[name]['generation'] == bundle[name]['generation'], 'Reader roots changed during probe')
        print('COMPOSITION_PROBE_DONE mode=%s readers=%s elapsed_sec=%.2f' %
              (mode, len(names), time.monotonic() - started), flush=True)
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

    def profile(self):
        mode = self.env.get('NIX_XD_PROFILE_MODE', 'store')
        require(mode in ('store', 'execution'), 'PROFILE_MODE must be store or execution')
        samples = int(self.env.get('NIX_XD_PROFILE_SAMPLES', '1'))
        require(1 <= samples <= 3, 'PROFILE_SAMPLES must be 1..3')
        names = sorted(self.plan['workloads'])
        before = self.batch([{'name': name, 'action': 'roots'} for name in names])
        report = {'sourceRevision': self.plan['sourceRevision'], 'mode': mode, 'samples': samples, 'placements': {}}
        for place in sorted(self.plan['placements']):
            name = next(name for name in names if self.plan['workloads'][name]['placement'] == place)
            state = json.loads(self.control(name, 'inspect'))
            require(state['active'] and state['generations'][state['active']]['status'] == 'active', 'Reader is not active: ' + name)
            unit = self.control(name, 'container-name')
            require(re.fullmatch(r'nix-xd-[a-z0-9-]+', unit), 'Invalid reader container name')
            command, env = self.transport_command(place, name)
            print('COMPOSITION_PROFILE_START placement=%s reader=%s samples=%s' % (place, name, samples), flush=True)
            baseline_start = time.monotonic()
            run(command, env, True, 'true\n', timeout=30)
            baseline = time.monotonic() - baseline_start
            print('PROFILE_TRANSPORT placement=%s real_sec=%.3f' % (place, baseline), flush=True)
            script = self.profile_script(unit, state['target'], samples, mode)
            started = time.monotonic()
            output = run(command, env, True, script, timeout=samples * 8 * 70 + 30)
            print(output, end='', flush=True)
            path = self.root / ('profile-' + mode + '-' + place + '.log')
            path.write_text(output)
            records, timings = [], {}
            for line in output.splitlines():
                if line.startswith('PROFILE_TIME '):
                    fields = dict(item.split('=', 1) for item in line.split()[1:])
                    timings[(fields['stage'], fields['sample'])] = {key: float(fields[key])
                        for key in ('real_sec', 'user_sec', 'sys_sec')}
                if line.startswith('PROFILE_RESULT '):
                    fields = dict(item.split('=', 1) for item in line.split()[1:])
                    require((fields['stage'], fields['sample']) in timings, 'Missing command timing')
                    fields.update(timings[(fields['stage'], fields['sample'])])
                    records.append(fields)
            require(len(records) == samples * 8, 'Incomplete profile measurements: ' + place)
            require('PROFILE_READER_UNCHANGED=true' in output.splitlines(), 'Reader changed during profiling')
            report['placements'][place] = {'reader': name, 'transport_sec': baseline,
                'elapsed_sec': time.monotonic() - started, 'results': records, 'log': str(path)}
        after = self.batch([{'name': name, 'action': 'roots'} for name in names])
        require(before == after, 'Reader generations or roots changed during profiling')
        report['result'] = 'measured'
        write_json(self.root / ('profile-' + mode + '.json'), report)
        failed = [(place, record) for place, data in report['placements'].items() for record in data['results']
                  if record['exit'] != '0']
        require(not failed, 'Profile includes failed or timed-out commands; inspect profile logs and profile.json')
        print('COMPOSITION_PROFILE_RESULT=passed placements=3 readers=3 roots=unchanged')

    @staticmethod
    def profile_script(unit, boot, samples, mode="store"):
        q = shlex.quote
        header = ('set -Eeuo pipefail\nexport LC_ALL=C\nunit=' + q(unit) + '\n' +
                  'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + q(boot) + '\n')
        prelude = header + r'''test "$(podman info --format '{{.Host.Security.Rootless}}')" = true
command -v timeout >/dev/null
cid="$(podman inspect "$unit" --format '{{.Id}}')"
test "$(podman inspect "$unit" --format '{{.State.Running}}')" = true
printf 'PROFILE_CONTAINER_ID=%s\n' "$cid"
measure() {
  local stage="$1" sample="$2" rc
  shift 2
  printf 'PROFILE_BEGIN reader=%s stage=%s sample=%s\n' "$unit" "$stage" "$sample" >&2
  TIMEFORMAT="PROFILE_TIME stage=$stage sample=$sample real_sec=%R user_sec=%U sys_sec=%S"
  set +e
  { time timeout --signal=TERM --kill-after=5s 60s "$@"; } 2>&1
  rc=$?
  set -e
  printf 'PROFILE_RESULT stage=%s sample=%s exit=%s\n' "$stage" "$sample" "$rc"
}
'''
        commands = r'''  measure shell-baseline "$sample" /usr/bin/true
  measure podman-inspect "$sample" podman inspect "$unit" --format '{{.State.Running}}'
  measure alpine-exec "$sample" podman exec "$unit" /bin/true
  measure alpine-shell "$sample" podman exec "$unit" /bin/sh -c ':'
  measure shared-hello "$sample" podman exec "$unit" /usr/local/bin/hello
  measure nix-version "$sample" podman exec "$unit" /usr/local/bin/nix --version
  measure nix-query "$sample" podman exec "$unit" /bin/sh -ec 'hello=$(readlink /usr/local/bin/hello); nix path-info "${hello%/bin/hello}"'
  measure nix-query-offline "$sample" podman exec "$unit" /bin/sh -ec 'hello=$(readlink /usr/local/bin/hello); nix --offline path-info "${hello%/bin/hello}"'
'''
        if mode == "execution":
            commands = r'''  measure guest-true "$sample" /usr/bin/true
  measure guest-shell "$sample" /bin/bash --noprofile --norc -c ':'
  measure podman-inspect "$sample" podman inspect "$unit" --format '{{.State.Running}}'
  measure alpine-true "$sample" podman exec "$unit" /bin/true
  measure alpine-shell "$sample" podman exec "$unit" /bin/sh -c ':'
  measure busybox-true "$sample" podman exec "$unit" /bin/busybox true
  measure busybox-shell "$sample" podman exec "$unit" /bin/busybox sh -c ':'
  measure busybox-shell-clean-env "$sample" podman exec --env ENV= --env BASH_ENV= "$unit" /bin/busybox sh -c ':'
'''
        return prelude + 'for sample in ' + ' '.join(str(n + 1) for n in range(samples)) + '; do\n' + commands + r'''
done
test "$(podman inspect "$unit" --format '{{.Id}}')" = "$cid"
printf 'PROFILE_READER_UNCHANGED=true\n'
'''

    def application(self):
        revision = self.owner('cat', self.flake + '/.nix-xd-source-revision')
        require(revision == self.env.get('NIX_XD_WORKLOAD_REV'), 'Stage the current committed application source first')
        run_id = uuid.uuid4().hex[:12]
        root = '/nix/home/nixuser/.local/state/nix-xd/application-redis-' + revision + '-' + run_id
        write_json(self.root / 'application.json', {'result': 'building', 'applicationRoot': root})
        print('APPLICATION_BUILD_START package=applicationRedis root=' + root, flush=True)
        app = self.owner('nix', 'build', '--no-write-lock-file', '--print-out-paths', '--out-link', root,
                         self.flake + '#applicationRedis')
        require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+', app), 'Invalid application closure')
        names = sorted(self.plan['workloads'])
        before = self.batch([{'name': name, 'action': 'roots'} for name in names])
        report = {'application': app, 'applicationRoot': root, 'sourceRevision': revision,
                  'compositionRevision': self.plan['sourceRevision'], 'placements': {}}
        write_json(self.root / 'application.json', dict(report, result='running'))
        for place in sorted(self.plan['placements']):
            name = next(name for name in names if self.plan['workloads'][name]['placement'] == place)
            state = json.loads(self.control(name, 'inspect'))
            require(state['active'] and state['generations'][state['active']]['status'] == 'active', 'Reader not active')
            unit = self.control(name, 'container-name')
            require(re.fullmatch(r'nix-xd-[a-z0-9-]+', unit), 'Invalid reader identity')
            variables = {'unit': unit, 'expected_boot': state['target'], 'app': app, 'requests': '100',
                         'directory': '/run/nixuser/redis-app-' + run_id}
            payload = 'set -Eeuo pipefail\n' + '\n'.join(key + '=' + shlex.quote(value) for key, value in variables.items()) + '\n'
            payload += (REPO / 'qualifiers/redis-application.sh').read_text()
            command, env = self.transport_command(place, name)
            print('APPLICATION_PLACEMENT_START placement=%s reader=%s' % (place, name), flush=True)
            started = time.monotonic()
            output = run(command, env, True, payload, timeout=1000)
            elapsed = time.monotonic() - started
            print(output, end='', flush=True)
            (self.root / ('application-' + place + '.log')).write_text(output)
            require('APPLICATION_RESULT=passed' in output.splitlines() and
                    'APPLICATION_CLEANUP=passed' in output.splitlines(), 'Application acknowledgement missing')
            timings = [dict(item.split('=', 1) for item in line.split()[1:])
                       for line in output.splitlines() if line.startswith('APPLICATION_TIME ')]
            startup = sum(float(item['real_sec']) for item in timings if item['stage'] in ('server-start', 'readiness'))
            report['placements'][place] = {'reader': name, 'elapsed_sec': elapsed, 'output': output,
                'startup_control_sec': startup, 'timings': timings}
            write_json(self.root / 'application.json', dict(report, result='running'))
            print('APPLICATION_PLACEMENT_DONE placement=%s elapsed_sec=%.2f' % (place, elapsed), flush=True)
        after = self.batch([{'name': name, 'action': 'roots'} for name in names])
        require(before == after, 'Reader roots or generations changed during application test')
        self.owner('rm', '--', root)
        report['result'] = 'passed'
        report['applicationRootRetained'] = False
        write_json(self.root / 'application.json', report)
        print('COMPOSITION_APPLICATION_RESULT=passed placements=3 roots=unchanged')

    def cancel(self):
        path = self.root / 'composition.lock'
        with path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                print('COMPOSITION_CANCEL_RESULT=idle')
                return
            require(shutil.which('lsof'), 'Cancellation requires lsof to identify the existing lock holder')
            found = subprocess.run(['lsof', '-t', '--', str(path)], text=True, capture_output=True)
            require(found.returncode == 0, 'Cannot identify the locked composition; interrupt its original terminal')
            candidates = {int(pid) for pid in found.stdout.split() if pid.isdigit()} - {os.getpid()}
            processes = {}
            for line in subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True).splitlines():
                columns = line.strip().split(None, 2)
                if len(columns) == 3:
                    processes[int(columns[0])] = (int(columns[1]), columns[2])
            holders = []
            for pid in candidates:
                command = processes.get(pid, (None, ''))[1]
                try:
                    arguments = shlex.split(command)
                except ValueError:
                    continue
                if any(argument in ('lib/compose_runtime.py', str(REPO / 'lib/compose_runtime.py'))
                       for argument in arguments) and arguments[-1] in ('plan', 'prepare', 'start', 'status', 'qualify', 'stop', 'profile', 'application'):
                    holders.append(pid)
            require(len(holders) == 1, 'Cannot uniquely identify the composition controller; no processes signalled')
            pid = holders[0]
            # Freeze only the lock-owning controller so it cannot schedule more work.
            os.kill(pid, signal.SIGSTOP)
            try:
                table = subprocess.check_output(['ps', '-axo', 'pid=,ppid='], text=True)
                children = {}
                for line in table.splitlines():
                    child, parent = map(int, line.split())
                    children.setdefault(parent, []).append(child)
                def descendants(parent):
                    for child in children.get(parent, []):
                        yield from descendants(child)
                        yield child
                for child in descendants(pid):
                    try:
                        os.kill(child, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                os.kill(pid, signal.SIGTERM)
            finally:
                try:
                    os.kill(pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    print('COMPOSITION_CANCEL_RESULT=passed controller_pid=%s roots=retained' % pid)
                    return
                except BlockingIOError:
                    time.sleep(0.2)
            raise ValueError('Controller termination requested but lock remains held; no roots released')

    def execute(self, phase):
        self.resolve(phase == 'plan', stopping=phase in ('stop', 'profile', 'application'))
        names = sorted(self.plan['workloads'])
        if phase in ('prepare', 'start', 'qualify', 'stop'):
            write_json(self.root / 'qualification.json', {'result': 'unqualified', 'phase': phase})
        if phase in ('start', 'qualify', 'profile', 'application'):
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
        elif phase == 'profile':
            self.profile()
        elif phase == 'application':
            self.application()
        print('COMPOSITION_PHASE_RESULT=passed phase=' + phase)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('plan', 'prepare', 'start', 'status', 'qualify', 'stop', 'cancel', 'profile', 'application'))
    args = parser.parse_args()
    require(sys.version_info >= (3, 9), 'Host qualification requires Python 3.9 or newer')
    runtime = Runtime(os.environ)
    if args.phase == 'cancel':
        runtime.cancel()
        return
    with (runtime.root / 'composition.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another composition phase is still running. Interrupt its original terminal or run make composition-cancel, then composition-stop. Do not delete the lock file.') from None
        runtime.execute(args.phase)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print('composition error: ' + str(error), file=sys.stderr)
        sys.exit(1)
