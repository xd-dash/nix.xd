#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
GENERATION = "a" * 64
MOCK = r'''#!/usr/bin/env python3
import json, os
from pathlib import Path
import subprocess, sys
kind = Path(sys.argv[0]).name
args = sys.argv[1:]
if kind == 'uname':
    print('Darwin' if args == ['-s'] else 'arm64')
    sys.exit(0)
if kind == 'ssh':
    if args[-1] == 'cat /proc/sys/kernel/random/boot_id':
        print('12345678-1234-1234-1234-123456789abc')
        sys.exit(0)
    payload = sys.stdin.read()
    if os.environ.get('SSH_FAIL') == '1': sys.exit(42)
    if os.environ.get('SSH_NO_ACK') == '1': sys.exit(0)
    sys.exit(subprocess.run([os.environ['TEST_BASH'], '-se'], input=payload, text=True).returncode)
assert kind == 'podman', kind
assert args[:2] == ['--connection', 'coreos-arm64'], args
args = args[2:]
if args[:3] == ['exec', 'nix-xd-arm', 'uname']:
    print('aarch64'); sys.exit(0)
if args[:2] == ['inspect', 'nix-xd-arm']:
    print('nix-xd-arm-store'); sys.exit(0)
assert args[:2] == ['exec', 'nix-xd-arm'], args
args = args[2:]
if args[0] == 'sh': sys.exit(0)
assert args[:2] == ['nix', 'run'], args
arguments = args[args.index('--') + 1:]
action = arguments[0]
with open(os.environ['CALLS'], 'a') as record:
    record.write(json.dumps(arguments) + '\n')
generation = 'a' * 64
if action in ['begin-activate', 'active-generation', 'begin-stop', 'confirm-active', 'confirm-stopped']:
    print(generation)
elif action == 'inspect': print('{}')
elif action.startswith('guest-'):
    marker = {'guest-activate': 'WORKLOAD_ACTIVATED', 'guest-check': 'WORKLOAD_CHECKED', 'guest-stop': 'WORKLOAD_STOPPED'}[action]
    print('echo ' + marker + '=' + generation)
else: raise AssertionError(arguments)
'''


class Transport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.shell = os.environ.get('NIX_XD_TEST_BASH') or shutil.which('bash')
        for name in ['podman', 'ssh', 'uname']:
            path = self.bin / name
            path.write_text(MOCK)
            path.chmod(0o755)
        state = self.root / 'coreos/starwisp'
        state.mkdir(parents=True)
        (state / 'manifest.txt').write_text('port=2222\n')
        (state / 'build.txt').write_text('shared_nix_volume=nix-xd-arm-store\n')
        (state / 'known_hosts').write_text('fixture\n')
        self.key = self.root / 'key'
        self.key.write_text('fixture\n')
        self.calls = self.root / 'calls'
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        TEST_BASH=self.shell, CALLS=str(self.calls),
                        NIX_XD_PROVIDER='podman', NIX_XD_MACHINE='coreos-arm64',
                        NIX_XD_SCOPE='nix-xd-arm', NIX_XD_SYSTEM='aarch64-linux',
                        NIX_XD_WORKLOAD='starwisp-probe', NIX_XD_WORKLOAD_GENERATION='',
                        COREOS_PROFILE='starwisp', COREOS_GUEST_USER='wisp', COREOS_SSH_PORT='2222',
                        COREOS_STATE_ROOT=str(self.root / 'coreos'), COREOS_SSH_KEY=str(self.key))

    def invoke(self, action, **extra):
        return subprocess.run([self.shell, str(REPO / 'bin/nix-xd-workload'), action],
                              env=dict(self.env, **extra), text=True, capture_output=True)

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_default_and_explicit_generation_all_operations(self):
        for selection in ['', GENERATION]:
            for action, intent, confirmation in [('activate', 'begin-activate', 'confirm-active'),
                                                  ('check', 'active-generation', None),
                                                  ('stop', 'begin-stop', 'confirm-stopped')]:
                result = self.invoke(action, NIX_XD_WORKLOAD_GENERATION=selection)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.recorded()
                selected = [c for c in calls if c[0] == intent][-1]
                self.assertEqual('--generation' in selected, bool(selection))
                if selection:
                    self.assertEqual(selected[selected.index('--generation') + 1], selection)
                if confirmation:
                    self.assertEqual(calls[-1][0], confirmation)
                self.calls.unlink()

    def test_lost_guest_reply_does_not_confirm_activation_or_release(self):
        for action in ['activate', 'stop']:
            for fault in ['SSH_FAIL', 'SSH_NO_ACK']:
                result = self.invoke(action, **{fault: '1'})
                self.assertNotEqual(result.returncode, 0)
                calls = self.recorded()
                self.assertFalse(any(c[0].startswith('confirm-') for c in calls))
                self.calls.unlink()


if __name__ == '__main__':
    unittest.main()
