#!/usr/bin/env python3
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

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


if __name__ == '__main__': unittest.main()
