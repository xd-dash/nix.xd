#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin/nix-xd-builder-store-profile"


class ProfilePlan(unittest.TestCase):
    def run_plan(self, stores, **variables):
        env = dict(os.environ, BUILDER_CHROOT_STORES=stores, NIX_XD_SCOPE="owner",
                   NIX_XD_STORE_VOLUME="owner-store", **variables)
        return subprocess.run(["bash", str(SCRIPT), "plan"], cwd=ROOT, env=env,
                              text=True, capture_output=True)

    def test_multiple_independent_writers(self):
        result = self.run_plan("grumble=grumble-store test=test-store")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("authoritative=owner-store", result.stdout)
        self.assertIn("name=grumble volume=grumble-store path=/stores/grumble rw=true", result.stdout)
        self.assertIn("name=test volume=test-store path=/stores/test rw=true", result.stdout)

    def test_rejects_conflicts_and_invalid_config(self):
        for stores in ("grumble=owner-store", "grumble=x test=x", "grumble=x grumble=y",
                       "grumble", "../oops=x", "grumble=x:rw", "grumble=x\ntest=y"):
            with self.subTest(stores=stores):
                self.assertNotEqual(self.run_plan(stores).returncode, 0)

    def test_rejects_unsafe_namespace_options(self):
        self.assertNotEqual(self.run_plan("grumble=x", BUILDER_CHROOT_NAMESPACE="unconfined").returncode, 0)


if __name__ == "__main__":
    unittest.main()
