#!/usr/bin/env python3
"""Exercise the host/owner boundary without requiring a running VM."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class OwnerBuild(unittest.TestCase):
    def test_build_uses_owner_toolchain_and_copies_only_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            (root / 'bin/nix-xd-wisp-go').write_text((REPO / 'bin/nix-xd-wisp-go').read_text())
            fake = root / 'podman'
            fake.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
 *"nix shell"*) cat > "$PAYLOAD" ;;
 *" cat "*) printf '#!/bin/sh\\nexit 0\\n' ;;
 *) exit 91 ;;
esac
''')
            fake.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       CALLS=str(root / 'calls'), PAYLOAD=str(root / 'payload'),
                       WISP_SMOKE_REV='a' * 40, NIX_XD_SCOPE='owner',
                       NIX_XD_MACHINE='test', NIX_XD_PROVIDER='podman')
            result = subprocess.run(['bash', str(root / 'bin/nix-xd-wisp-go'), 'build'],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = (root / 'calls').read_text()
            self.assertIn('/workspaces/nix.xd#wispGoTools', calls)
            self.assertEqual(calls.count(' cat '), 2)
            self.assertNotIn('.ssh', calls)
            payload = (root / 'payload').read_text()
            self.assertIn('CGO_ENABLED=0', payload)
            self.assertIn('WISP_REQUIRE_UNIX=1 go test -race', payload)
            self.assertEqual((root / '.state/wisp-go/revision').read_text().strip(), 'a' * 40)
            self.assertTrue((root / '.state/wisp-go/smoke').stat().st_mode & 0o100)

    def test_tools_declared_in_flake(self):
        flake = (REPO / 'flake.nix').read_text()
        self.assertIn('wispGoTools = pkgs.buildEnv', flake)
        self.assertIn('pkgs.go_1_26 pkgs.gcc', flake)


if __name__ == '__main__':
    unittest.main()
