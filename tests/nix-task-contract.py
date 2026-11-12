#!/usr/bin/env python3
"""Verify generic Nix task dispatch without a running container."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TASK = Path(__file__).resolve().parents[1] / "bin/nix-xd-task"


class NixTaskContract(unittest.TestCase):
    def test_run_without_args(self):
        self.run_case("run", "#coreos-plan-vm1", [], "#coreos-plan-vm1")

    def test_run_with_args(self):
        self.run_case("run", "#coreos-plan-vm1", ["one", "two"], "#coreos-plan-vm1")

    def test_nested_check_attribute(self):
        self.run_case("build", "#checks.aarch64-linux.coreos-plan", [], "#checks.aarch64-linux.coreos-plan")

    def run_case(self, action, target, args, suffix):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            podman = root / "podman"
            podman.write_text("""#!/bin/sh
case " $* " in
  *" uname -m "*) printf '%s\\n' aarch64 ;;
  *) printf '%s\\n' "$*" >> "$CALLS" ;;
esac
""")
            podman.chmod(0o755)
            env = dict(
                os.environ,
                PATH=str(root) + ":" + os.environ["PATH"],
                CALLS=str(root / "calls"),
                NIX_XD_MACHINE="test",
                NIX_XD_PROVIDER="podman",
                NIX_XD_SCOPE="owner",
                NIX_XD_SYSTEM="aarch64-linux",
                NIX_XD_FLAKE="agni20261111/local/fatline",
                NIX_XD_TARGET=target,
                NIX_XD_ARGS=" ".join(args),
            )
            result = subprocess.run(["bash", str(TASK), action], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            call = (root / "calls").read_text().strip()
            self.assertIn("/workspaces/agni20261111/local/fatline" + suffix, call)
            if action == "run":
                self.assertIn(" run --no-write-lock-file ", call)
                if args:
                    self.assertTrue(call.endswith("-- " + " ".join(args)))
                else:
                    self.assertFalse(call.endswith(" --"))


if __name__ == "__main__":
    unittest.main()
