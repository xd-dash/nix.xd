#!/usr/bin/env python3
"""Profile routing, private credentials and bounded bridge failure cleanup."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import fatline_host_link as host
import fatline_cross as cross
from fatline_logmash import subscriber_environment
from builder_store_qualify import mount


class Profiles(unittest.TestCase):
    def test_vm2_routes_to_its_own_placement(self):
        calls = []
        plan = {'schema':1, 'scope':'fatline-arm-vm2', 'system':'aarch64-linux', 'storeDomain':'common',
            'sources':{'agni':{'repository':'dash-xd/agni','revision':'a'*40}},
            'ingress':{'transport':'ssh-tcp-nginx-unix','hostPort':26379,'guestProxyPort':16379},
            'placement':{'name':'vm2'}}
        class Runtime:
            def __init__(self, env): self.flake = '/flake'
            def owner(self, *args):
                calls.append(args)
                return 'aarch64' if args == ('uname','-m') else json.dumps(plan)
            def transport_command(self, place, name):
                calls.append((place, name))
                return ['ssh'], {'COREOS_STATE_ROOT':'vm2'}
        with tempfile.TemporaryDirectory() as directory, patch.object(host, 'REPO', Path(directory)), patch.object(host, 'Runtime', Runtime), patch.dict(os.environ, {'NIX_XD_SYSTEM':'aarch64-linux', 'NIX_XD_FATLINE_PROFILE':'vm2','NIX_XD_FATLINE_SCOPE':'fatline-arm-vm2'}):
            link = host.HostLink()
            self.assertEqual(link.env['COREOS_STATE_ROOT'], 'vm2')
            self.assertEqual(calls[-1], ('vm2', 'transport'))
            self.assertTrue(any('/flake#fatlinePlans.aarch64-linux.vm2' in call for call in calls))

    def test_credential_environment_is_profile_specific(self):
        env = subscriber_environment({}, 'private', 'us:vm2')
        self.assertEqual(env, {'LOGMASH_REDIS_US_VM2_USERNAME':'subscriber','LOGMASH_REDIS_US_VM2_PASSWORD':'private'})
        self.assertNotIn('LOGMASH_REDIS_US_VM1_PASSWORD', env)

    def test_bridge_setup_failure_cleans_only_owned_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'credentials').mkdir()
            (root / 'credentials/subscriber').write_text('a'*64)
            source = SimpleNamespace(command=['ssh','source','bash -se'], env={}, state={'incoming':'/home/wisp/.local/state/nix-xd/incoming-scope'})
            target = SimpleNamespace(root=root, env={}, config={'placement':{'sshPort':2223}})
            commands = []
            def run(argv, env, capture=False, input_text=None, timeout=None):
                commands.append((argv, input_text))
                return ''
            with patch.object(cross, 'run', side_effect=run), patch.object(cross, 'tunnel_command', return_value=['smoke','wisp']), patch.object(cross.subprocess, 'Popen', side_effect=OSError('startup failed')):
                with self.assertRaisesRegex(OSError, 'startup failed'):
                    cross.direction(source, target, '/smoke', '/nix/store/smoke', root)
            self.assertIn('mkdir /home/wisp/.local/state/nix-xd/nix-xd-cross-', commands[0][1])
            self.assertIn('systemctl --user stop nix-xd-cross-', commands[1][1])
            self.assertIn('rmdir -- /home/wisp/.local/state/nix-xd/nix-xd-cross-', commands[2][1])
            self.assertTrue(all('a'*64 not in repr(argv) for argv, script in commands))

    def test_peer_requires_exact_read_only_volume_binding(self):
        item = {'Mounts':[{'Destination':'/peer/agni','Name':'legacy-store','RW':False}]}
        mount(item, '/peer/agni', 'legacy-store', False)
        with self.assertRaisesRegex(ValueError, 'Unexpected store mount'):
            mount(item, '/peer/agni', 'legacy-store', True)
        with self.assertRaisesRegex(ValueError, 'Unexpected store mount'):
            mount(item, '/peer/agni', 'other-store', False)


if __name__ == '__main__': unittest.main()
