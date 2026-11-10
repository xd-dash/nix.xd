#!/usr/bin/env python3
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from fatline_services import Services
from fatline_host_link import HostLink


class Lifecycle(unittest.TestCase):
    def make(self, directory):
        root = Path(directory)
        calls = []
        link = SimpleNamespace(root=root, state={'aclDigest':'old'}, state_path=root/'transport.json',
            retain=lambda: calls.append(('retain-base',)),
            runtime=SimpleNamespace(owner=lambda *args: calls.append(args)))
        services = Services(link)
        services.state = {'root':'/registered-services-root','bundle':'/nix/store/services','status':'active'}
        services.guest = lambda action: calls.append(('guest',action))
        return services, calls

    def test_stop_releases_application_root_only_after_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            services.execute('stop')
            self.assertEqual(calls, [('guest','stop'), ('rm','-f','--','/registered-services-root')])
            self.assertEqual(services.state['status'], 'stopped')
            self.assertEqual(services.link.state['aclDigest'], 'old')

    def test_failed_stop_retains_application_root(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            def lost(action): raise ValueError('lost acknowledgement')
            services.guest = lost
            with self.assertRaises(ValueError): services.execute('stop')
            self.assertEqual(calls, [])
            self.assertEqual(services.state['status'], 'active')

    def test_activation_updates_acl_binding_only_after_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            services.state['aclDigest'] = 'new'
            services.retain = lambda: None
            def lost(action): raise ValueError('lost acknowledgement')
            services.guest = lost
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError): services.execute('activate')
            self.assertEqual(services.link.state['aclDigest'], 'old')
            self.assertEqual(services.state['status'], 'activating')
            self.assertEqual(json.loads((services.root/'qualification.json').read_text())['result'], 'running')

    def test_base_stop_refuses_live_application_services(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'services').mkdir()
            (root/'services/state.json').write_text('{"status":"active"}')
            link = HostLink.__new__(HostLink)
            link.root = root
            with self.assertRaisesRegex(ValueError, 'fatline-services-stop'):
                link.execute('stop')

    def test_refresh_preserves_credentials_and_both_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            services.link.scope = 'scope'
            services.link.command = ['ssh']
            services.link.env = {}
            services.link.state['boot'] = 'same-boot'
            services.state.update(status='activating', source={'revision':'old'})
            metadata = {'schema':1,'logmaRev':'logma','skymillRev':'skymill','ratelimiterRev':'limiter','probe':'new-probe'}
            services.state['metadata'] = dict(metadata, probe='old-probe')
            source = {'revision':'b'*40,'refreshFrom':['old'],'package':'coreos-services-vm1'}
            services.selection = lambda: source
            services.retain = lambda: calls.append(('retain-both',))
            for name in ('guest.sh','render.py','acl-policy.json','render-users-acl.py'):
                (services.root/name).write_text('unchanged\n')
            credentials = services.root/'credentials'; credentials.mkdir()
            (credentials/'secret').write_text('preserve-this-value')
            def owner(*args):
                calls.append(args)
                if args[0] == 'cat':
                    return json.dumps(metadata) if args[1].endswith('metadata.json') else 'unchanged'
                return '/nix/store/' + 'a'*32 + '-services'
            services.link.runtime.owner = owner
            with patch('fatline_services.run', return_value='FATLINE_SERVICES_REFRESH_SAFE=true\n'), contextlib.redirect_stdout(io.StringIO()):
                services.refresh()
            self.assertEqual((credentials/'secret').read_text(), 'preserve-this-value')
            self.assertEqual(services.state['retiredRoots'], [{'root':'/registered-services-root','bundle':'/nix/store/services'}])
            self.assertEqual(services.state['metadata']['probe'], 'new-probe')
            self.assertFalse(any(call[0] == 'rm' for call in calls))
            self.assertEqual(calls[-1], ('retain-both',))

    def test_refresh_refuses_missing_inactive_guest_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            services.state.update(status='activating', source={'revision':'old'})
            services.link.scope = 'scope'
            services.link.command, services.link.env = ['ssh'], {}
            services.link.state['boot'] = 'boot'
            services.selection = lambda: {'refreshFrom':['old'],'revision':'b'*40}
            with patch('fatline_services.run', return_value=''):
                with self.assertRaisesRegex(ValueError, 'not confirmed'):
                    services.refresh()
            self.assertEqual(calls, [])
            self.assertEqual(services.state['root'], '/registered-services-root')

    def test_probe_refresh_does_not_rebind_live_applications(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            services.link.scope = 'scope'
            services.retain = lambda: None
            source = {'revision':'c'*40,'package':'coreos-services-vm1'}
            services.selection = lambda key: source
            old = {'schema':1,'logmaRev':'logma','skymillRev':'skymill','ratelimiterRev':'limiter',
                   'logma':'old-logma','skymill':'old-skymill','probe':'old-probe'}
            services.state['metadata'] = dict(old)
            new = dict(old, probe='/nix/store/'+'a'*32+'-probe/bin/fatline-services-probe', logma='new-unused-logma')
            def owner(*args):
                calls.append(args)
                return json.dumps(new) if args[0] == 'cat' else '/nix/store/'+'b'*32+'-bundle'
            services.link.runtime.owner = owner
            with contextlib.redirect_stdout(io.StringIO()): services.refresh_probe()
            self.assertEqual(services.state['metadata'], old)
            self.assertEqual(services.state['status'], 'active')
            self.assertEqual(services.state['qualificationProbe']['executable'], new['probe'])
            self.assertFalse(any(call[0] in ('rm','systemctl') for call in calls))

    def test_configuration_updates_only_logma_and_records_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            services, calls = self.make(directory)
            services.state['metadata'] = {'logma':'keep-runtime-binary'}
            selected = {'revision':'new-config'}
            services.selection = lambda key: selected
            def refresh(): services.state['qualificationProbe'] = {'source':selected,'bundle':'/nix/store/probe'}
            services.refresh_probe = refresh
            services.link.runtime.owner = lambda *args: '#!/bin/bash\necho configure\n'
            with contextlib.redirect_stdout(io.StringIO()): services.configure_logma()
            self.assertEqual(calls,[('guest','configure-logma')])
            self.assertEqual(services.state['configurationAdapter']['status'],'applied')
            self.assertEqual(services.state['metadata']['logma'],'keep-runtime-binary')
            self.assertEqual(services.state['status'],'active')
            with contextlib.redirect_stdout(io.StringIO()): services.configure_logma()
            self.assertEqual(calls[-1],('guest','status'))


if __name__ == '__main__': unittest.main()
