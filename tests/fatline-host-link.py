#!/usr/bin/env python3
import hashlib
import os
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from fatline_host_link import HostLink


class Adapter(unittest.TestCase):
    def test_roots_release_only_after_acknowledged_guest_stop(self):
        link = HostLink.__new__(HostLink)
        with tempfile.TemporaryDirectory() as directory:
            link.root = Path(directory)
            link.state_path = link.root / 'state.json'
            link.state = {'roots':['root-one','root-two'], 'status':'prepared'}
            calls = []
            class Owner:
                def owner(self, *args): calls.append(('owner', args))
            link.runtime = Owner()
            link.guest = lambda action: calls.append(('guest', action))
            with contextlib.redirect_stdout(io.StringIO()): link.execute('stop')
            self.assertEqual(calls[0], ('guest','stop'))
            self.assertEqual(len(calls), 3)
            self.assertEqual(json.loads(link.state_path.read_text())['status'], 'stopped')

    def test_failed_stop_retains_roots(self):
        link = HostLink.__new__(HostLink)
        with tempfile.TemporaryDirectory() as directory:
            link.root = Path(directory)
            link.state = {'roots':['root-one'], 'status':'prepared'}
            calls = []
            class Owner:
                def owner(self, *args): calls.append(args)
            link.runtime = Owner()
            def lost_reply(action): raise ValueError('lost guest acknowledgement')
            link.guest = lost_reply
            with self.assertRaisesRegex(ValueError, 'lost guest'):
                link.execute('stop')
            self.assertEqual(calls, [])

    def test_zero_exit_without_stop_acknowledgement_is_rejected(self):
        link = HostLink.__new__(HostLink)
        link.scope = 'fatline-arm-vm1'
        link.command, link.env = ['unused'], {}
        link.state = {'metadata':{'port':16379, 'redis':'/nix/store/redis', 'nginx':'/nix/store/nginx',
            'clientLinux':'/nix/store/client/bin/host-link'}, 'boot':'boot', 'incoming':'/incoming',
            'archive':'/nix/store/rootfs', 'aclDigest':'digest'}
        with tempfile.TemporaryDirectory() as directory:
            link.root = Path(directory)
            (link.root / 'guest.sh').write_text('true\n')
            with patch('fatline_host_link.run', return_value=''), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'acknowledgement missing'):
                    link.guest('stop')

    def test_adapter_refresh_checks_digest_and_preserves_runtime(self):
        link = HostLink.__new__(HostLink)
        script = '#!/bin/bash\necho fixed\n'
        adapter = {'repository':'dash-xd/agni', 'contract':'fatline-host-link-v1',
            'compatibleRuntimeRevision':'runtime', 'revision':'b' * 40,
            'sha256':hashlib.sha256(script.encode()).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            link.root = Path(directory)
            link.state_path = link.root / 'state.json'
            link.state = {'agniRev':'runtime', 'roots':['protected'], 'status':'prepared'}
            link.scope = 'scope'
            link.profile = 'vm1'
            link.state['composition'] = {'revision':'pinned'}
            (link.root / 'guest.sh').write_text('old')
            class Owner:
                flake = '/workspaces/nix.xd'
                def owner(self, *args):
                    if args[0] == 'cat':
                        return 'selected' if args[1].endswith('source-revision') else script.strip()
                    if '--json' in args:
                        return json.dumps({'scope':'scope','guestAdapter':adapter})
                    return '/nix/store/source/local/fatline'
            link.runtime = Owner()
            with patch('fatline_host_link.resolve', return_value=({'scope':'scope', 'guestAdapter':adapter}, {'revision':'pinned'})), \
                 patch.dict(os.environ, {'NIX_XD_WORKLOAD_REV':'selected', 'NIX_XD_SYSTEM':'aarch64-linux'}), \
                 contextlib.redirect_stdout(io.StringIO()):
                link.refresh_adapter()
                self.assertEqual((link.root / 'guest.sh').read_text(), script)
                self.assertEqual(link.state['roots'], ['protected'])
                adapter['sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    link.refresh_adapter()
                self.assertEqual((link.root / 'guest.sh').read_text(), script)

    def test_artifact_owner_is_pinned_and_not_a_moving_branch(self):
        plan = (Path(__file__).resolve().parents[1] / 'compositions/fatline-coreos.nix').read_text()
        self.assertRegex(plan, r'revision = "[a-f0-9]{40}"')
        source = (Path(__file__).resolve().parents[1] / 'lib/fatline_host_link.py').read_text()
        self.assertIn("reference = 'github:dash-xd/agni/' + self.agni_rev", source)
        self.assertNotIn('pkill', source)
        self.assertIn("'ExitOnForwardFailure=yes'", source)
        self.assertIn("'UserKnownHostsFile='", (Path(__file__).resolve().parents[1] / 'lib/compose_runtime.py').read_text())


if __name__ == '__main__':
    unittest.main()
