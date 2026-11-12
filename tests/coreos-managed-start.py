#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + 'a' * 64
CID = 'b' * 64
MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\n')
if args[:2] == ['machine', 'inspect']: print('running'); sys.exit(0)
args = args[2:]
if args[0] == 'info': print('aarch64'); sys.exit(0)
if args[0] == 'image': print('sha256:' + 'a'*64); sys.exit(0)
if args[0] == 'inspect':
    status = os.environ['VM_STATUS']
    if status == 'missing': sys.exit(1)
    if args[-1] == '{{.State.Status}}': print(status)
    elif args[-1] == '{{.Id}}': print('b'*64)
    elif '/host-nix' in args[-1]: print('nix-xd-arm-store:false')
    elif args[-1] == '{{.Image}}': print(('sha256:' if os.environ.get('IMAGE_PREFIX') else '')+'a'*64)
    else: raise AssertionError(args)
elif args[0] == 'start': print('coreos-starwisp')
elif args[0] == 'run':
    if '--detach' in args: print('b'*64)
    if 'create' in args: Path(os.environ['COREOS_STATE_ROOT'], 'starwisp/overlay.qcow2').write_text('overlay')
elif args[0] in ['volume', 'rm', 'logs']: pass
else: raise AssertionError(args)
'''


class ManagedStart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / 'coreos/starwisp'
        self.state.mkdir(parents=True)
        self.record = root / 'calls'
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        tool = bin_dir / 'podman'
        tool.write_text(MOCK)
        tool.chmod(0o755)
        (self.state / 'base.qcow2').write_bytes(b'disk')
        (self.state / 'config.ign').write_bytes(b'ignition')
        (self.state / 'build.txt').write_text('runner=' + IMAGE + '\ndisk_sha256=' + hashlib.sha256(b'disk').hexdigest() +
            '\nignition_sha256=' + hashlib.sha256(b'ignition').hexdigest() + '\nshared_nix_volume=nix-xd-arm-store\n')
        self.env = dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'], CALLS=str(self.record),
                        COREOS_STATE_ROOT=str(root / 'coreos'), COREOS_PROFILE='starwisp',
                        COREOS_NIX_STORE_VOLUME='nix-xd-arm-store', NIX_XD_MACHINE='coreos-arm64',
                        NIX_XD_SCOPE='nix-xd-arm', VM_STATUS='running')

    def manifest(self, managed=True):
        (self.state / 'overlay.qcow2').write_text('overlay')
        (self.state / 'manifest.txt').write_text('port=2222\nrunner=' + IMAGE + '\n' +
            ('container_id=' + CID + '\n' if managed else ''))

    def run_start(self, status):
        return subprocess.run(['bash', str(REPO / 'bin/nix-xd-coreos-podman'), 'start'],
                              env=dict(self.env, VM_STATUS=status), capture_output=True, text=True)

    def test_running_is_reused_without_boot(self):
        self.manifest()
        result = self.run_start('running')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('reused=true', result.stdout)
        self.env['IMAGE_PREFIX'] = '1'
        prefixed = self.run_start('running')
        self.assertEqual(prefixed.returncode, 0, prefixed.stderr)
        calls = self.record.read_text()
        self.assertNotIn('--detach', calls)
        self.assertNotIn('["--connection", "coreos-arm64", "start"', calls)

    def test_exited_managed_container_is_started(self):
        self.manifest()
        result = self.run_start('exited')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('["--connection", "coreos-arm64", "start", "coreos-starwisp"]', self.record.read_text())

    def test_unknown_running_vm_and_orphaned_overlay_are_refused(self):
        self.manifest(managed=False)
        self.assertNotEqual(self.run_start('running').returncode, 0)
        self.assertNotEqual(self.run_start('missing').returncode, 0)
        self.assertTrue((self.state / 'overlay.qcow2').exists())

    def test_second_vm_shares_artifacts_without_copying_disk(self):
        primary = self.state
        second = primary.parent / "second" / "starwisp"
        self.env["COREOS_ARTIFACT_STATE"] = str(primary)
        self.env["COREOS_STATE_ROOT"] = str(second.parent)
        result = self.run_start('missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((second / "base.qcow2").exists())
        self.assertTrue((second / "build.txt").exists())
        self.assertIn("/artifacts/base.qcow2", self.record.read_text())
        self.assertIn('artifact_state=' + str(primary.resolve()), (second / "manifest.txt").read_text())

    def test_default_state_survives_dated_checkout_selection(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(self.env, HOME=home)
            env.pop('COREOS_STATE_ROOT')
            result = subprocess.run(['bash', str(REPO / 'bin/nix-xd-coreos-podman'), 'start'],
                                    env=dict(env, VM_STATUS='missing'), capture_output=True, text=True)
            stable = Path(home) / '.local/state/nix-xd/coreos/starwisp'
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Missing base.qcow2', result.stderr)
            self.assertTrue(stable.is_dir())
            self.assertFalse((stable / '.managed-start.lock').exists())

    def test_missing_state_reports_missing_artifacts_not_lock_contention(self):
        import shutil
        shutil.rmtree(self.state)
        result = self.run_start('missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing base.qcow2', result.stderr)
        self.assertNotIn('already running', result.stderr)
        self.assertTrue(self.state.is_dir())
        self.assertFalse((self.state / '.managed-start.lock').exists())

    def test_fresh_boot_records_container_identity(self):
        result = self.run_start('missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('container_id=' + CID, (self.state / 'manifest.txt').read_text())


if __name__ == '__main__':
    unittest.main()
