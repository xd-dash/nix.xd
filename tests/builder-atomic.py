#!/usr/bin/env python3
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AtomicProfile(unittest.TestCase):
    def test_seccomp_derives_from_restrictive_default(self):
        source = ROOT / "bin/nix-xd-builder-seccomp.py"
        spec = importlib.util.spec_from_file_location("builder_seccomp", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = {"defaultAction": "SCMP_ACT_ERRNO", "architectures": ["SCMP_ARCH_AARCH64"],
                    "syscalls": [{"names": ["read", "sethostname"], "action": "SCMP_ACT_ALLOW"}]}
        policy = module.render(original)
        self.assertEqual(policy["defaultAction"], "SCMP_ACT_ERRNO")
        self.assertEqual(policy["architectures"], original["architectures"])
        self.assertEqual(policy["syscalls"][0]["names"], ["read"])
        self.assertEqual(policy["syscalls"][-1]["names"], ["setdomainname", "sethostname"])
        self.assertEqual(original["syscalls"][0]["names"], ["read", "sethostname"])
        with self.assertRaises(ValueError):
            module.render({"defaultAction": "SCMP_ACT_ALLOW", "syscalls": []})

    def test_probe_uses_effective_oci_profile_not_unavailable_info_field(self):
        prestart = (ROOT / "bin/nix-xd-builder-profile-prestart").read_text()
        self.assertIn("OCIConfigPath", prestart)
        self.assertIn("seccomp-probe", prestart)
        self.assertNotIn("SeccompProfilePath", prestart)
        self.assertIn("trap cleanup EXIT", prestart)
        makefile = (ROOT / "mk/builder-store-profile.mk").read_text()
        self.assertIn("@set -e; if [[ '$(INITIAL_PROFILE)' == 1 ]]", makefile)

    def test_quadlet_generated_before_first_start(self):
        env = dict(os.environ, NIX_XD_STORE_VOLUME="fixture-store",
                   NIX_XD_PEER_STORES="",
                   NIX_XD_INITIAL_CHROOT_STORES="grumble=fixture-grumble experiments=fixture-experiments",
                   NIX_XD_INITIAL_SECCOMP_PATH=os.environ["HOME"] +
                   "/.config/nix-xd/seccomp/fixture-nix-chroot.json")
        result = subprocess.run(["bash", "-c", """
            source lib/builder-stores.sh
            builder_stores_init fixture
            builder_quadlet fixture localhost/nix-xd:arm64 "Fixture"
        """], cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        quadlet = result.stdout
        for expected in ("Volume=fixture-store:/nix",
                         "Volume=fixture-grumble:/stores/grumble",
                         "Volume=fixture-experiments:/stores/experiments",
                         "Unmask=/proc/*", "SeccompProfile="):
            self.assertIn(expected, quadlet)
        self.assertNotIn("Privileged=true", quadlet)
        self.assertNotIn("seccomp=unconfined", quadlet)

    def test_bootstrap_uses_initial_declarations_without_post_start_apply(self):
        arm = (ROOT / "arm/bootstrap-podman.sh").read_text()
        prestart = arm.index("nix-xd-builder-profile-prestart")
        render = arm.index('builder_quadlet "$scope"')
        start = arm.index('systemctl --user start "$scope.service"')
        self.assertLess(prestart, render)
        self.assertLess(render, start)
        makefile = (ROOT / "mk/builder-store-profile.mk").read_text()
        self.assertIn("INITIAL_CHROOT_STORES", makefile)
        self.assertIn("INITIAL_PROFILE", makefile)
        self.assertIn("builder-store-profile-complete", makefile)

    def test_atomic_scope_is_independent_of_retained_qualification(self):
        script = (ROOT / "bin/nix-xd-builder-store-qualify-atomic").read_text()
        self.assertIn("nix-xd-arm-atomic-qualify", script)
        self.assertNotIn("nix-xd-arm-chroot-qualify", script)
        self.assertIn("BUILDER_ATOMIC_PROFILE_RESULT=passed", script)


if __name__ == "__main__":
    unittest.main()
