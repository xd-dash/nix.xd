#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScopedVolumes(unittest.TestCase):
    def test_probe_reuses_shared_rootless_namespace_without_reentering_it(self):
        for target, current, expected in [('user:[123]', 'user:[123]', 'host'),
                                          ('user:[456]', 'user:[123]', 'container:builder')]:
            result = subprocess.run(['bash', '-eu', '-c',
                                     'source lib/tenant-storage.sh; tenant_probe_userns "$1" "$2" builder',
                                     '--', target, current], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)
        result = subprocess.run(['bash', '-eu', '-c',
                                 'source lib/tenant-storage.sh; tenant_probe_userns invalid "user:[123]" builder'],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def run_controller(self, labels, operation='tenant_volume_remove fixture-qualify a private', status='0'):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'calls'
            env = dict(os.environ, TEST_LABELS=labels, TEST_STATUS=status, TEST_RECORD=str(record))
            script = '''source lib/tenant-storage.sh
podman() {
  printf '%s\\n' "$*" >> "$TEST_RECORD"
  if [[ $* == volume\\ inspect* ]]; then printf '%s\\n' "$TEST_LABELS"; return; fi
  return "$TEST_STATUS"
}
''' + operation
            result = subprocess.run(['bash', '-eu', '-c', script], cwd=ROOT, env=env,
                                    text=True, capture_output=True)
            return result, record.read_text() if record.exists() else ''

    def test_delete_requires_all_declared_identity_labels(self):
        good = 'true|tenant-store|disposable|fixture-qualify|a|private'
        result, calls = self.run_controller(good)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('volume rm fixture-qualify-a-private', calls)
        for bad in ('', good.replace('|a|', '|b|'), good.replace('disposable', 'reusable'),
                    good.replace('fixture-qualify', 'other-qualify')):
            with self.subTest(labels=bad):
                result, calls = self.run_controller(bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('volume rm', calls)

    def test_in_use_delete_failure_propagates_without_force_or_file_access(self):
        result, calls = self.run_controller('true|tenant-store|disposable|fixture-qualify|a|private', status='2')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('--force', calls)
        self.assertNotIn('run ', calls)
        self.assertNotIn('mountpoint', calls.lower())

    def test_invalid_scope_or_traversal_fails_before_podman(self):
        for operation in ('tenant_volume_remove ordinary a private',
                          'tenant_volume_remove fixture-qualify ../b private',
                          'tenant_volume_remove fixture-qualify a ../private'):
            result, calls = self.run_controller('', operation)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, '')

    def test_create_attaches_disposable_scope_tenant_and_store_metadata(self):
        result, calls = self.run_controller('', 'tenant_volume_create fixture-qualify a private')
        self.assertEqual(result.returncode, 0, result.stderr)
        for value in ('io.nix-xd.scope=fixture-qualify', 'io.nix-xd.tenant=a',
                      'io.nix-xd.store=private', 'io.nix-xd.lifecycle=disposable'):
            self.assertIn(value, calls)


if __name__ == '__main__':
    unittest.main()
