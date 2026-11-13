#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin/nix-xd-builder-store-qualify-fresh"
CLEAN = ROOT / "bin/nix-xd-builder-store-maintenance"


class FreshProfileContract(unittest.TestCase):
    def fixture(self, directory):
        tools = Path(directory) / "bin"
        tools.mkdir()
        record = Path(directory) / "commands"
        for name, body in {
            "uname": 'case "$1" in -s) echo Darwin;; -m) echo arm64;; esac',
            "make": 'printf "make %s\\n" "$*" >> "$TEST_COMMANDS"',
            "podman": '''
printf "podman %s\\n" "$*" >> "$TEST_COMMANDS"
case "$*" in
  *"machine inspect"* ) echo running; exit 0 ;;
  *"volume exists"* ) exit 0 ;;
  * ) exit 1 ;;
esac
''',
        }.items():
            path = tools / name
            path.write_text("#!/usr/bin/env bash\nset -eu\n" + body + "\n")
            path.chmod(0o755)
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                   TEST_COMMANDS=str(record), NIX_XD_MACHINE="fixture",
                   NIX_XD_PROVIDER="podman", NIX_XD_SYSTEM="aarch64-linux",
                   NIX_XD_PEER_STORES="", NIX_XD_CHROOT_SELINUX="keep",
                   BUILDER_CHROOT_NAMESPACE="1", BUILDER_CHROOT_SYSCALLS="1")
        return env, record

    def test_existing_volume_refuses_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            env, record = self.fixture(directory)
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env,
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("qualification-volume-already-exists", result.stderr)
            self.assertNotIn("bootstrap-builder-profile", record.read_text())

    def test_cleanup_needs_exact_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            env, record = self.fixture(directory)
            result = subprocess.run(["bash", str(CLEAN), "clean-qualify"],
                                    cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("QUALIFY_RESET_CONFIRM=ERASE:", result.stderr)
            self.assertFalse(record.exists())


if __name__ == "__main__":
    unittest.main()
