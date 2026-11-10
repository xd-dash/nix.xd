#!/usr/bin/env python3
"""Build and qualify Agni's first scoped CoreOS-to-host transport contract."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
import tempfile

from compose_runtime import Runtime, run, write_json
from compositions import require

REPO = Path(__file__).resolve().parents[1]


class HostLink:
    def __init__(self):
        self.runtime = Runtime(os.environ)
        actual = self.runtime.owner('uname', '-m')
        require((os.environ['NIX_XD_SYSTEM'], actual) in (('aarch64-linux','aarch64'), ('x86_64-linux','x86_64')), 'Owner architecture mismatch')
        self.scope = os.environ.get('NIX_XD_FATLINE_SCOPE', 'fatline-arm-vm1')
        require(re.fullmatch(r'[a-z][a-z0-9-]{0,31}', self.scope), 'Invalid Fatline scope')
        self.profile = os.environ.get('NIX_XD_FATLINE_PROFILE', 'vm1')
        require(self.profile in ('vm1', 'vm2'), 'Select Fatline profile vm1 or vm2')
        require(self.scope == 'fatline-arm-' + self.profile, 'Scope does not match selected profile')
        self.root = REPO / '.state/fatline' / self.scope
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.state_path = self.root / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else None
        self.config = self.state['plan'] if self.state else json.loads(self.runtime.owner('nix', 'eval', '--json',
            '--no-write-lock-file', self.runtime.flake + '#fatlinePlans.' + os.environ['NIX_XD_SYSTEM'] + '.' + getattr(self, 'profile', 'vm1')))
        require(self.config['storeDomain'] == 'common', 'Unsupported store domain')
        require(self.config['schema'] == 1 and self.config['scope'] == self.scope and
                self.config['system'] == os.environ['NIX_XD_SYSTEM'], 'Invalid Fatline plan binding')
        source = self.config['sources']['agni']
        require(source['repository'] == 'dash-xd/agni' and re.fullmatch(r'[a-f0-9]{40}', source['revision']),
                'Invalid pinned Agni source')
        require(self.config['ingress'] == {'transport':'ssh-tcp-nginx-unix', 'hostPort':16379 if self.profile == 'vm1' else 26379, 'guestProxyPort':16379},
                'Unsupported ingress profile')
        self.agni_rev = source['revision']
        self.runtime.plan = {'placements': {self.profile: self.config['placement']},
                             'workloads': {'transport': {'placement': self.profile}}}
        self.command, self.env = self.runtime.transport_command(self.profile, 'transport')

    def guest(self, action):
        require(self.state, 'Run fatline-prepare first')
        metadata = self.state['metadata']
        variables = dict(action=action, scope=self.scope, port=str(metadata['port']), boot=self.state['boot'],
            incoming=self.state['incoming'], archive=self.state['archive'], redis=metadata['redis'],
            nginx=metadata['nginx'], client=metadata['clientLinux'], acl_digest=self.state['aclDigest'])
        script = 'set -Eeuo pipefail\n' + '\n'.join(k + '=' + shlex.quote(v) for k, v in variables.items()) + '\n'
        script += (self.root / 'guest.sh').read_text()
        output = run(self.command, self.env, True, script, timeout=600)
        print(output, end='', flush=True)
        expected = {'prepare':'FATLINE_HOST_LINK_PREPARED=true', 'start':'FATLINE_HOST_LINK_STARTED=true',
            'status':'FATLINE_HOST_LINK_STATUS=passed', 'check':'FATLINE_HOST_LINK_SECURITY=passed',
            'publish':'HOST_LINK_PUBLISH=passed', 'stop':'FATLINE_HOST_LINK_STOPPED=true'}
        require(expected[action] in output.splitlines(), 'Guest acknowledgement missing; roots retained')
        return output

    def retain(self):
        require(self.state, 'Run fatline-prepare first')
        for root, path in zip(self.state['roots'], (self.state['bundle'], self.state['archive'])):
            self.runtime.owner('sh', '-ec',
                'test -e "$2"; if [ -L "$1" ]; then test "$(readlink "$1")" = "$2"; else nix-store --realise --add-root "$1" "$2" >/dev/null; fi',
                'retain', root, path)

    def prepare(self):
        if self.state:
            require(self.state['status'] in ('prepared', 'stopped'), 'Existing partial scope requires explicit reconciliation')
            require(self.state['agniRev'] == self.agni_rev, 'Existing scope pins another Agni revision; migrate explicitly')
            self.retain()
            print('FATLINE_PREPARE=reused')
            return
        owner = self.runtime.owner
        staged = owner('cat', self.runtime.flake + '/.nix-xd-source-revision')
        require(staged == os.environ.get('NIX_XD_WORKLOAD_REV'), 'Stage the selected nix.xd revision first')
        suffix = '/nix/home/nixuser/.local/state/nix-xd/fatline-' + self.scope
        owner('mkdir', '-p', '/nix/home/nixuser/.local/state/nix-xd')
        source = self.config['sources']['agni']
        reference = 'github:dash-xd/agni/' + self.agni_rev + '?dir=' + source['flakeDirectory']
        print('FATLINE_BUILD_START agni=' + self.agni_rev, flush=True)
        bundle = owner('nix', 'build', '--no-write-lock-file', '--print-out-paths', '--out-link', suffix + '-bundle',
                       reference + '#' + source['package'])
        archive = owner('nix', 'build', '--no-write-lock-file', '--print-out-paths', '--out-link', suffix + '-rootfs',
                        self.runtime.flake + '#nixAlpineRootfs')
        for path in (bundle, archive):
            require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+', path), 'Invalid retained store output')
        metadata = json.loads(owner('cat', bundle + '/metadata.json'))
        require(metadata['scope'] == self.scope and metadata['port'] == 16379, 'Artifact binding mismatch')
        for name in ('guest.sh', 'render.py'):
            (self.root / name).write_text(owner('cat', bundle + '/' + name) + '\n')
        credentials = self.root / 'credentials'
        require(not credentials.exists(), 'Existing credentials require explicit reconciliation')
        run([sys.executable, str(self.root / 'render.py'), str(credentials), self.scope, '16379'], self.env)
        payload = os.urandom(24).hex()
        publisher = {'network':'unix', 'address':'/run/redis/redis.sock', 'username':'publisher',
            'passwordFile':'/run/credentials/publisher', 'scope':self.scope,
            'channel':self.scope + ':qualification', 'payload':payload}
        write_json(credentials / 'publisher.json', publisher)
        subscriber = dict(publisher, network='tcp', address='127.0.0.1:' + str(self.config['ingress']['hostPort']), username='subscriber',
                          passwordFile=str(credentials / 'subscriber'))
        write_json(credentials / 'subscriber.json', subscriber)
        client = metadata['clientDarwin'] if platform.system() == 'Darwin' else metadata['clientLinux']
        with (self.root / 'host-link').open('wb') as output:
            subprocess.run(self.runtime.podman + ['exec', self.runtime.scope, 'cat', client], stdout=output, check=True)
        os.chmod(self.root / 'host-link', 0o700)
        guest_home = run(self.command, self.env, True, 'printf "%s" "$HOME"\n', timeout=30).strip()
        require(re.fullmatch(r'/[A-Za-z0-9/_.-]+', guest_home), 'Unexpected guest home')
        incoming = guest_home + '/.local/state/nix-xd/incoming-' + self.scope
        boot = run(self.command, self.env, True, 'cat /proc/sys/kernel/random/boot_id\n', timeout=30).strip()
        self.state = {'aclDigest':hashlib.sha256((credentials / 'users.acl').read_bytes()).hexdigest(),
                      'policyDigest':(credentials / 'policy.sha256').read_text().strip(),
                      'plan':self.config, 'status':'preparing', 'metadata':metadata, 'archive':archive, 'bundle':bundle,
                      'agniRev':self.agni_rev, 'boot':boot, 'incoming':incoming,
                      'roots':[suffix + '-bundle', suffix + '-rootfs']}
        write_json(self.state_path, self.state)
        run(self.command, self.env, True, 'install -d -m 700 ' + shlex.quote(incoming) + '\n', timeout=30)
        options = self.command[2:-2]
        options = ['-P' if item == '-p' else item for item in options]
        files = [str(credentials / name) for name in ('users.acl', 'publisher', 'publisher.json', 'redis.conf', 'nginx.conf')]
        run(['scp', '-q', *options, *files, self.command[-2] + ':' + incoming + '/'], self.env)
        self.guest('prepare')
        self.state['status'] = 'prepared'
        write_json(self.state_path, self.state)
        print('FATLINE_PREPARE_RESULT=passed scope=' + self.scope)

    def refresh_adapter(self):
        require(self.state, 'Prepare the runtime before refreshing its guest adapter')
        staged = self.runtime.owner('cat', self.runtime.flake + '/.nix-xd-source-revision')
        require(staged == os.environ.get('NIX_XD_WORKLOAD_REV'), 'Stage the selected revision first')
        desired = json.loads(self.runtime.owner('nix', 'eval', '--json', '--no-write-lock-file',
            self.runtime.flake + '#fatlinePlans.' + os.environ['NIX_XD_SYSTEM'] + '.' + getattr(self, 'profile', 'vm1')))
        adapter = desired['guestAdapter']
        require(desired['scope'] == self.scope and adapter['repository'] == 'dash-xd/agni' and
                adapter['contract'] == 'fatline-host-link-v1' and
                adapter['compatibleRuntimeRevision'] == self.state['agniRev'] and
                re.fullmatch(r'[a-f0-9]{40}', adapter['revision']) and
                re.fullmatch(r'[a-f0-9]{64}', adapter['sha256']), 'Incompatible guest adapter')
        source = self.runtime.owner('nix', 'eval', '--raw', '--expr',
            '(builtins.getFlake "github:dash-xd/agni/' + adapter['revision'] +
            '?dir=local/fatline").outPath')
        require(re.fullmatch(r'/nix/store/[A-Za-z0-9._+/-]+', source), 'Invalid adapter source path')
        script = self.runtime.owner('cat', source + '/host-link/guest.sh') + '\n'
        require(hashlib.sha256(script.encode()).hexdigest() == adapter['sha256'], 'Guest adapter digest mismatch')
        # Only the script cache changes; running units, credentials and closure roots remain bound to the runtime.
        with tempfile.NamedTemporaryFile('w', dir=self.root, delete=False) as candidate:
            candidate.write(script)
            candidate.flush()
            os.fsync(candidate.fileno())
        os.replace(candidate.name, self.root / 'guest.sh')
        self.state['guestAdapter'] = adapter
        write_json(self.state_path, self.state)
        print('FATLINE_GUEST_ADAPTER_RESULT=passed revision=' + adapter['revision'])

    def qualify(self):
        self.retain()
        write_json(self.root / 'qualification.json', {'result':'running', 'scope':self.scope})
        self.guest('status')
        self.guest('check')
        tunnel_command = self.command[:-2] + ['-o','ExitOnForwardFailure=yes','-N','-L',
                          '127.0.0.1:' + str(self.config['ingress']['hostPort']) + ':127.0.0.1:16379', self.command[-2]]
        native = [str(self.root / 'host-link'), '--config', str(self.root / 'credentials/subscriber.json')]
        tunnel = subscriber = None
        with (self.root / 'tunnel.log').open('w') as tunnel_log, (self.root / 'subscriber.log').open('w') as subscriber_log:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as available:
                    available.bind(('127.0.0.1', self.config['ingress']['hostPort']))
                tunnel = subprocess.Popen(tunnel_command, env=self.env, stdin=subprocess.DEVNULL,
                    stdout=tunnel_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    require(tunnel.poll() is None, 'SSH tunnel failed; see tunnel.log')
                    try:
                        with socket.create_connection(('127.0.0.1', self.config['ingress']['hostPort']), timeout=1): break
                    except OSError:
                        time.sleep(0.2)
                else: raise ValueError('SSH forward readiness timed out')
                for mode in ('check', 'unauthenticated'):
                    result = run(native + ['--mode', mode], self.env, True, timeout=150)
                    print(result, end='', flush=True)
                    marker = 'HOST_LINK_ACL=passed' if mode == 'check' else 'HOST_LINK_UNAUTHENTICATED=denied'
                    require(marker in result.splitlines(), 'Host client acknowledgement missing')
                subscriber = subprocess.Popen(native + ['--mode','subscribe'], env=self.env,
                    stdout=subscriber_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    text = (self.root / 'subscriber.log').read_text()
                    if 'HOST_LINK_SUBSCRIBER_READY=true' in text: break
                    require(subscriber.poll() is None, 'Subscriber failed; see subscriber.log')
                    time.sleep(0.2)
                else: raise ValueError('Subscriber readiness timed out')
                self.guest('publish')
                require(subscriber.wait(timeout=130) == 0, 'Subscriber failed')
                text = (self.root / 'subscriber.log').read_text()
                print(text, end='', flush=True)
                require('HOST_LINK_MESSAGE=passed' in text, 'No authenticated host delivery')
            finally:
                for process in (subscriber, tunnel):
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
        write_json(self.root / 'qualification.json', {'result':'passed', 'scope':self.scope,
            'agniRev':self.state['agniRev'], 'logmaRev':self.state['metadata']['logmaRev'],
            'boot':self.state['boot'], 'aclDigest':self.state['aclDigest'], 'policyDigest':self.state['policyDigest'],
            'gate':'host-link-transport-only'})
        print('FATLINE_HOST_LINK_RESULT=passed full_fatline=false')

    def execute(self, action):
        if action == 'prepare': self.prepare()
        elif action == 'adapter-refresh': self.refresh_adapter()
        elif action == 'qualify': self.qualify()
        else:
            if action == 'start':
                self.retain()
                self.state['status'] = 'prepared'
                write_json(self.state_path, self.state)
            if action == 'stop':
                applications = self.root / 'services/state.json'
                if applications.exists():
                    status = json.loads(applications.read_text())['status']
                    require(status not in ('active','activating'),
                            'Stop application services with fatline-services-stop before stopping Redis')
            if action in ('start', 'stop'):
                write_json(self.root / 'qualification.json', {'result':'unqualified', 'phase':action})
            self.guest(action)
            if action == 'stop':
                for root in self.state['roots']:
                    self.runtime.owner('rm', '-f', '--', root)
                self.state['status'] = 'stopped'
                write_json(self.state_path, self.state)
                print('FATLINE_STOP_RESULT=passed roots=released')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare','start','status','qualify','stop','adapter-refresh'))
    args = parser.parse_args()
    runtime = HostLink()
    with (runtime.root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime.execute(args.action)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print('fatline host-link error: ' + str(error), file=sys.stderr)
        sys.exit(1)
