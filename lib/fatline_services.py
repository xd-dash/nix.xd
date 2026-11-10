#!/usr/bin/env python3
"""Compose pinned Agni application services with the qualified CoreOS transport."""
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


class Services:
    def __init__(self, link):
        self.link = link
        require(link.state, 'Prepare the existing Fatline transport first')
        self.root = link.root / 'services'
        self.root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.path = self.root / 'state.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else None

    def retain(self):
        require(self.state, 'Run fatline-services-prepare first')
        self.link.retain()
        retained = [{'root':self.state['root'], 'bundle':self.state['bundle']}] + self.state.get('retiredRoots', [])
        for generation in retained:
            self.link.runtime.owner('sh', '-ec',
                'test -e "$2"; if [ -L "$1" ]; then test "$(readlink "$1")" = "$2"; else nix-store --realise --add-root "$1" "$2" >/dev/null; fi',
                'retain', generation['root'], generation['bundle'])

    def selection(self):
        owner = self.link.runtime.owner
        staged = owner('cat', self.link.runtime.flake + '/.nix-xd-source-revision')
        require(staged == os.environ.get('NIX_XD_WORKLOAD_REV'), 'Stage the selected nix.xd revision first')
        plan = json.loads(owner('nix', 'eval', '--json', '--no-write-lock-file',
            self.link.runtime.flake + '#fatlinePlans.' + os.environ['NIX_XD_SYSTEM'] + '.host-link'))
        source = plan['services']
        require(source['repository'] == 'dash-xd/agni' and source['contract'] == 'coreos-services-v1' and
                re.fullmatch(r'[a-f0-9]{40}', source['revision']) and source['package'] == 'coreos-services-vm1',
                'Invalid application source binding')
        return source

    def prepare(self):
        owner = self.link.runtime.owner
        source = self.selection()
        if self.state:
            require(self.state['source'] == source, 'Prepared applications pin another revision')
            self.retain()
            print('FATLINE_SERVICES_PREPARE=reused')
            return
        root = '/nix/home/nixuser/.local/state/nix-xd/fatline-' + self.link.scope + '-services'
        bundle = owner('nix', 'build', '--no-write-lock-file', '--print-out-paths', '--out-link', root,
            'github:dash-xd/agni/' + source['revision'] + '?dir=local/fatline#' + source['package'])
        require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+', bundle), 'Invalid application bundle')
        for name in ('guest.sh', 'render.py', 'acl-policy.json', 'render-users-acl.py', 'metadata.json'):
            (self.root / name).write_text(owner('cat', bundle + '/' + name) + '\n')
        metadata = json.loads((self.root / 'metadata.json').read_text())
        policy = json.loads((self.root / 'acl-policy.json').read_text())
        require(policy['componentRevisions'] == {'logma':metadata['logmaRev'], 'skymill':metadata['skymillRev'],
                'ratelimiter':metadata['ratelimiterRev']}, 'Application source/ACL policy pin mismatch')
        run([sys.executable, str(self.root / 'render.py'), str(self.root), str(self.link.root / 'credentials'),
             str(self.root / 'credentials'), self.link.scope], self.link.env)
        self.state = {'source':source, 'bundle':bundle, 'root':root, 'metadata':metadata,
            'aclDigest':(self.root / 'credentials/digest').read_text().strip(),
            'policyDigest':hashlib.sha256((self.root / 'credentials/policy.json').read_bytes()).hexdigest(),
            'status':'prepared'}
        write_json(self.path, self.state)
        self.retain()
        print('FATLINE_SERVICES_PREPARE=passed')

    def refresh(self):
        require(self.state, 'Prepare application services first')
        source = self.selection()
        if self.state['source'] == source:
            self.retain()
            print('FATLINE_SERVICES_REFRESH=reused')
            return
        require(self.state['status'] in ('prepared','activating','stopped') and
                self.state['source']['revision'] in source.get('refreshFrom', []),
                'Stop services and select a declared compatible refresh before changing pins')
        link = self.link
        # A lost activation reply must not be mistaken for an inactive runtime.
        inspect = 'set -Eeuo pipefail\n' + 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(link.state['boot']) + '\n'
        inspect += 'test ! -e "$HOME/.local/state/nix-xd/fatline/' + link.scope + '/services/active"\n'
        for role in ('logma','skymill'):
            name = shlex.quote(link.scope + '-' + role)
            inspect += 'if podman container exists ' + name + '; then\n'
            inspect += 'podman inspect ' + name + " --format '{{.State.Running}}' | grep -Fxq false\nfi\n"
        inspect += 'echo FATLINE_SERVICES_REFRESH_SAFE=true\n'
        observed = run(link.command, link.env, True, inspect, timeout=60)
        require('FATLINE_SERVICES_REFRESH_SAFE=true' in observed.splitlines(), 'Inactive guest services were not confirmed')
        owner = link.runtime.owner
        root = '/nix/home/nixuser/.local/state/nix-xd/fatline-' + link.scope + '-services-' + source['revision']
        bundle = owner('nix', 'build', '--no-write-lock-file', '--print-out-paths', '--out-link', root,
            'github:dash-xd/agni/' + source['revision'] + '?dir=local/fatline#' + source['package'])
        require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+', bundle), 'Invalid refreshed application bundle')
        for name in ('guest.sh','render.py','acl-policy.json','render-users-acl.py'):
            require(owner('cat', bundle + '/' + name).strip() == (self.root / name).read_text().strip(),
                    'Refresh changes runtime/credential policy; explicit migration required')
        metadata = json.loads(owner('cat', bundle + '/metadata.json'))
        for key in ('schema','logmaRev','skymillRev','ratelimiterRev'):
            require(metadata[key] == self.state['metadata'][key], 'Refresh changes application component pins')
        previous = {'root':self.state['root'], 'bundle':self.state['bundle']}
        self.state.setdefault('retiredRoots', []).append(previous)
        self.state.update(source=source, root=root, bundle=bundle, metadata=metadata)
        write_json(self.path, self.state)
        write_json(self.root / 'metadata.json', metadata)
        self.retain()
        print('FATLINE_SERVICES_REFRESH=passed credentials=preserved previous_roots=retained')

    def guest(self, action):
        require(self.state, 'Prepare application services first')
        link = self.link
        incoming = link.state['incoming'] + '-services'
        if action == 'activate':
            run(link.command, link.env, True, 'install -d -m 700 ' + shlex.quote(incoming) + '\n', timeout=30)
            options = ['-P' if item == '-p' else item for item in link.command[2:-2]]
            files = [str(self.root / 'credentials' / name) for name in ('logma', 'skymill', 'bootstrap', 'users.acl')]
            run(['scp', '-q', '-r', *options, *files, link.command[-2] + ':' + incoming + '/'], link.env)
        variables = dict(action=action, scope=link.scope, boot=link.state['boot'], incoming=incoming,
            archive=link.state['archive'], old_acl_digest=link.state['aclDigest'], new_acl_digest=self.state['aclDigest'])
        variables.update({key:self.state['metadata'][key] for key in ('logma','skymill','probe')})
        script = 'set -Eeuo pipefail\n' + '\n'.join(key + '=' + shlex.quote(value) for key,value in variables.items()) + '\n'
        script += (self.root / 'guest.sh').read_text()
        output = run(link.command, link.env, True, script, timeout=1200)
        print(output, end='', flush=True)
        markers = {'activate':('FATLINE_SERVICES_ACTIVATED=passed','FATLINE_SERVICES_ACTIVATED=reused'),
            'qualify':('FATLINE_SERVICES_QUALIFICATION=passed',), 'status':('FATLINE_SERVICES_STATUS=passed private_http=true',),
            'stop':('FATLINE_SERVICES_STOPPED=passed',)}
        require(any(marker in output.splitlines() for marker in markers[action]), 'Missing guest acknowledgement; all roots retained')

    def execute(self, action):
        if action == 'refresh':
            self.refresh()
            return
        if action == 'prepare':
            self.prepare()
            return
        if action in ('activate','qualify'):
            self.retain()
        if action in ('activate','qualify'):
            write_json(self.root / 'qualification.json', {'result':'running','phase':action})
        if action == 'activate':
            for evidence in ('qualification.json','logmash-qualification.json'):
                write_json(self.link.root / evidence, {'result':'unqualified','phase':'services-activation'})
            self.state['status'] = 'activating'
            write_json(self.path, self.state)
            print('FATLINE_SERVICES_ACTIVATION_START redis_restart=required ephemeral_state=true', flush=True)
        self.guest(action)
        if action == 'activate':
            self.link.state['aclDigest'] = self.state['aclDigest']
            write_json(self.link.state_path, self.link.state)
            self.state['status'] = 'active'
            write_json(self.path, self.state)
        elif action == 'qualify':
            write_json(self.root / 'qualification.json', {'result':'passed','boot':self.link.state['boot'],
                'source':self.state['source'], 'components':self.state['metadata'],
                'aclDigest':self.state['aclDigest'],'policyDigest':self.state['policyDigest'],
                'gate':'coreos-services-single-vm','fullFatline':False})
            print('FATLINE_SERVICES_RESULT=passed full_fatline=false')
        elif action == 'stop':
            for generation in [{'root':self.state['root']}] + self.state.get('retiredRoots', []):
                self.link.runtime.owner('rm', '-f', '--', generation['root'])
            self.state['status'] = 'stopped'
            self.state['retiredRoots'] = []
            write_json(self.path, self.state)
            write_json(self.root / 'qualification.json', {'result':'unqualified','phase':'stopped'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare','refresh','activate','qualify','status','stop'))
    action = parser.parse_args().action
    link = HostLink()
    with (link.root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Services(link).execute(action)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Fatline services error: ' + str(error), file=sys.stderr)
        sys.exit(1)
