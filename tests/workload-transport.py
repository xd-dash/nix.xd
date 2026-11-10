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
    if args[-1].startswith('umask 077; cat >'):
        Path(os.environ['SHELL_PAYLOAD']).write_text(sys.stdin.read()); sys.exit(0)
    if args[-1].startswith('bash ') and args[-1] != 'bash -se':
        assert '-tt' in args
        payload = Path(os.environ['SHELL_PAYLOAD']).read_text()
    else:
        payload = sys.stdin.read()
    if os.environ.get('SSH_FAIL') == '1': sys.exit(42)
    if os.environ.get('SSH_FAIL_PHASE') and '# ACTION=' + os.environ['SSH_FAIL_PHASE'] in payload: sys.exit(42)
    if os.environ.get('SSH_NO_ACK') == '1': sys.exit(0)
    sys.exit(subprocess.run([os.environ['TEST_BASH'], '-se'], input=payload, text=True).returncode)
assert kind == 'podman', kind
if args[:3] == ['machine', 'ssh', 'coreos-arm64']:
    if args[-1] == 'cat /proc/sys/kernel/random/boot_id':
        print('12345678-1234-1234-1234-123456789abc'); sys.exit(0)
    sys.exit(subprocess.run([os.environ['TEST_BASH'], '-se'], input=sys.stdin.read(), text=True).returncode)
assert args[:2] == ['--connection', 'coreos-arm64'], args
args = args[2:]
if args[:2] == ['volume', 'inspect']:
    print('/volumes/nix-xd-arm-store'); sys.exit(0)
if args[:3] == ['exec', 'nix-xd-arm', 'uname']:
    print('aarch64'); sys.exit(0)
if args[:2] == ['inspect', 'nix-xd-arm']:
    print('nix-xd-arm-store'); sys.exit(0)
if args[:2] == ['exec', '-i']: args.pop(1)
assert args[:2] == ['exec', 'nix-xd-arm'], args
args = args[2:]
if args[0] == 'sh': sys.exit(0)
if args[0].endswith('/bin/nix-xd-workload-control'):
    arguments = args[1:]
else:
    assert args[:2] == ['nix', 'run'], args
    arguments = args[args.index('--') + 1:]
action = arguments[0]
with open(os.environ['CALLS'], 'a') as record:
    record.write(json.dumps(arguments) + '\n')
generation = 'a' * 64
phase_file = Path(os.environ['CONTROLLER_STATE'])
phase = phase_file.read_text() if phase_file.exists() else 'snapshot'
tx = 'f' * 32
transitions = {'recreate-record-before': 'stop', 'recreate-stopped': 'start',
               'recreate-activated': 'check', 'recreate-checked': 'verify', 'confirm-recreated': 'done',
               'abandon-recreate': 'abandoned'}
if action in ['begin-recreate', 'pending-recreation']: print(tx)
elif action == 'recreate-phase': print(phase)
elif action in transitions:
    phase_file.write_text(transitions[action]); print(generation)
elif action == 'recreate-record-after': sys.stdin.read(); print(generation)
elif action in ['guest-snapshot-before', 'guest-snapshot-after']:
    print('# ACTION=' + action + '\necho RECREATE_TRANSACTION=' + tx)
elif action.startswith('guest-recreate-'):
    marker = {'guest-recreate-stop': 'WORKLOAD_STOPPED', 'guest-recreate-activate': 'WORKLOAD_ACTIVATED',
              'guest-recreate-check': 'WORKLOAD_CHECKED'}[action]
    print('# ACTION=' + action + '\necho ' + marker + '=' + generation)
elif action in ['status-selection', 'begin-activate', 'active-generation', 'begin-stop', 'confirm-active', 'confirm-stopped']:
    print('none' if action == 'status-selection' and os.environ.get('ACTIVE_NONE') else generation)
elif action in ['inspect', 'summary']: print('{}')
elif action == 'placement': print(os.environ.get('NIX_XD_WORKLOAD_PLACEMENT', 'guest'))
elif action == 'runtime-path': print('starwisp-probe/' + generation)
elif action == 'guest-shell': print('echo WORKLOAD_SHELL_FIXTURE=passed')
elif action.startswith('guest-'):
    marker = {'guest-activate': 'WORKLOAD_ACTIVATED', 'guest-check': 'WORKLOAD_CHECKED', 'guest-stop': 'WORKLOAD_STOPPED', 'guest-status': 'WORKLOAD_STATUS_OK'}[action]
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
                        TEST_BASH=self.shell, CALLS=str(self.calls), CONTROLLER_STATE=str(self.root / "phase"), SHELL_PAYLOAD=str(self.root / "shell-payload"),
                        NIX_XD_PROVIDER='podman', NIX_XD_MACHINE='coreos-arm64',
                        NIX_XD_SCOPE='nix-xd-arm', NIX_XD_STORE_VOLUME='nix-xd-arm-store', NIX_XD_SYSTEM='aarch64-linux',
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
                                                  ('stop', 'begin-stop', 'confirm-stopped'),
                                                  ('status', 'active-generation', None)]:
                result = self.invoke(action, NIX_XD_WORKLOAD_GENERATION=selection)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.recorded()
                selected = [c for c in calls if c[0] == intent][-1]
                self.assertEqual('--generation' in selected, bool(selection) or action == 'status')
                if selection:
                    self.assertEqual(selected[selected.index('--generation') + 1], selection)
                if confirmation:
                    self.assertEqual(calls[-1][0], confirmation)
                self.calls.unlink()

    def test_shell_preserves_interactive_stdin_and_does_not_confirm_or_log_it(self):
        result = self.invoke('shell')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('WORKLOAD_SHELL_FIXTURE=passed', result.stdout)
        self.assertFalse(any(c[0].startswith('confirm-') for c in self.recorded()))
        dry = subprocess.run(['make', '-sn', 'workload-shell', 'ARCH=arm64'], cwd=REPO,
                             text=True, capture_output=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertNotIn('nix-xd-log', dry.stdout)

    def test_recreation_resumes_after_failed_replacement_without_releasing_roots(self):
        failed = self.invoke('recreate', SSH_FAIL_PHASE='guest-recreate-activate')
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((self.root / 'phase').read_text(), 'start')
        self.assertFalse(any(c[0] == 'confirm-stopped' for c in self.recorded()))
        resumed = self.invoke('recreate')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn('WORKLOAD_RECREATE_RESULT=passed', resumed.stdout)
        calls = self.recorded()
        self.assertEqual(sum(c[0] == 'guest-recreate-stop' for c in calls), 1)
        self.assertFalse(any(c[0] == 'confirm-stopped' for c in calls))

    def test_explicit_abandon_uses_acknowledged_stop(self):
        result = self.invoke('recreate-abandon')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [c[0] for c in self.recorded()]
        self.assertLess(calls.index('abandon-recreate'), calls.index('guest-stop'))
        self.assertLess(calls.index('guest-stop'), calls.index('confirm-stopped'))

    def test_host_reader_uses_machine_transport_and_explicit_export(self):
        result = self.invoke('activate', NIX_XD_WORKLOAD_PLACEMENT='host', COREOS_SSH_KEY='/missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        activation = next(c for c in self.recorded() if c[0] == 'begin-activate')
        self.assertEqual(activation[activation.index('--store-export') + 1], '/volumes/nix-xd-arm-store/store')

    def test_recreation_pause_keeps_roots_and_defers_replacement(self):
        result = self.invoke('recreate', NIX_XD_RECREATE_PAUSE='after-stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = [c[0] for c in self.recorded()]
        self.assertIn('recreate-stopped', actions)
        self.assertNotIn('guest-recreate-activate', actions)
        self.assertNotIn('confirm-stopped', actions)
        self.assertIn('WORKLOAD_RECREATE_PAUSED=after-stop', result.stdout)

    def test_resolved_controller_avoids_nix_run(self):
        result = self.invoke('check', NIX_XD_WORKLOAD_CONTROLLER='/nix/store/' + 'f' * 32 + '-controller/bin/nix-xd-workload-control')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('guest-check', [c[0] for c in self.recorded()])

    def test_stopped_status_does_not_require_a_guest_connection(self):
        result = self.invoke('status', ACTIVE_NONE='1', COREOS_SSH_KEY='/missing/key')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('WORKLOAD_STATUS=stopped', result.stdout)

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
