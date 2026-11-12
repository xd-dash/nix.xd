#!/usr/bin/env python3
"""Host artifact transport must verify the Nix owner's exact bytes."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from composition_artifact import export_executable

STORE = '/nix/store/' + 'a' * 32 + '-smoke-darwin-arm64'
REV = 'b' * 40
PAYLOAD = b'fake-mach-o-fixture'


class Artifact(unittest.TestCase):
    def test_verified_atomic_export(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'smoke'
            output = ('ARTIFACT_SOURCE_REV=' + REV + '\nARTIFACT_STORE_PATH=' + STORE +
                      '\nARTIFACT_SHA256=' + hashlib.sha256(PAYLOAD).hexdigest() +
                      '\nARTIFACT_TARGET=darwin-arm64')
            calls = []
            runtime = SimpleNamespace(scope='nix-xd-arm', podman=['podman', '--connection', 'coreos-arm64'],
                                      env={}, owner=lambda *args: (calls.append(args), output)[1])
            def copy(argv, **kwargs):
                self.assertEqual(argv[-2], 'nix-xd-arm:' + STORE)
                Path(argv[-1]).write_bytes(PAYLOAD)
                return subprocess.CompletedProcess(argv, 0)
            with patch('composition_artifact.subprocess.run', side_effect=copy):
                result = export_executable(runtime, 'github:dash-xd/agni/' + REV + '?dir=local/fatline',
                                           'smoke-host-artifact', destination, 'darwin-arm64')
            self.assertEqual(destination.read_bytes(), PAYLOAD)
            self.assertEqual(result['sourceRevision'], REV)
            self.assertEqual(result['sha256'], hashlib.sha256(PAYLOAD).hexdigest())
            self.assertEqual(calls[0][0:4], ('nix', 'run', '--no-write-lock-file', '--no-update-lock-file'))

    def test_mutable_artifact_flake_ref_is_rejected_before_execution(self):
        runtime = SimpleNamespace(scope='owner', podman=['podman'], env={},
                                  owner=lambda *args: self.fail('owner must not run'))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'exact-revision'):
                export_executable(runtime, 'github:dash-xd/agni/main?dir=local/fatline',
                                  'smoke-host-artifact', Path(directory) / 'smoke', 'darwin-arm64')

    def test_tampered_copy_is_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'smoke'
            destination.write_bytes(b'existing')
            output = ('ARTIFACT_SOURCE_REV=' + REV + '\nARTIFACT_STORE_PATH=' + STORE +
                      '\nARTIFACT_SHA256=' + hashlib.sha256(PAYLOAD).hexdigest() +
                      '\nARTIFACT_TARGET=darwin-arm64')
            runtime = SimpleNamespace(scope='owner', podman=['podman'], env={}, owner=lambda *args: output)
            def bad_copy(argv, **kwargs):
                Path(argv[-1]).write_bytes(b'tampered')
                return subprocess.CompletedProcess(argv, 0)
            with patch('composition_artifact.subprocess.run', side_effect=bad_copy):
                with self.assertRaisesRegex(ValueError, 'digest differs'):
                    export_executable(runtime, '/workspaces/agni20261111/local/fatline',
                                      'smoke-host-artifact', destination, 'darwin-arm64')
            self.assertEqual(destination.read_bytes(), b'existing')
            self.assertEqual(list(destination.parent.glob('.artifact-*')), [])


if __name__ == '__main__':
    unittest.main()
