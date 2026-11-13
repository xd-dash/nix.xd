#!/usr/bin/env python3
"""Shoal runtime fails closed where no real subnet exists."""
import argparse
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import shoal_runtime as shoal


class ShoalRuntimeTests(unittest.TestCase):
    def test_stages_select_bounded_guests(self):
        self.assertEqual(shoal.names("farcaster"), ("farcaster",))
        self.assertEqual(shoal.names("world1"), ("farcaster", "world1"))
        with self.assertRaises(ValueError):
            shoal.names("world7")

    def test_network_cannot_pass_without_real_dual_stack_and_egress_policy(self):
        with self.assertRaisesRegex(ValueError, "shared-dual-stack-subnet"):
            shoal.network(None)

    def test_guest_probe_enforces_9p_ro_and_two_rootless_containers(self):
        script = shoal.GUEST_PROBE
        self.assertIn('FSTYPE --mountpoint', script)
        self.assertIn('= 9p', script)
        self.assertIn('*,ro,*', script)
        self.assertIn('Rootless', script)
        self.assertIn('for n in a b', script)
        self.assertIn('dst=/nix/store,ro', script)
        self.assertIn('--network none', script)
        self.assertIn('SHOAL_GUEST_STORAGE=passed', script)
        self.assertIn('SHOAL_EXPECTED_BUSYBOX_SHA256', script)

    def test_host_attestation_requires_correct_provider_and_store(self):
        args = argparse.Namespace(
            ssh_key="/tmp/mock-key", owner="nix-xd-arm", machine="coreos-arm64",
            provider="container", flake="/workspaces/nix.xd",
            state_root="/unavailable", stage="farcaster",
            ssh_user="wisp", farcaster_port=2222, world1_port=2223,
        )
        fake_rootfs = "/nix/store/" + "a" * 32 + "-rootfs"
        calls = []
        def fake_run(argv, input_text=None, timeout=120):
            calls.append(argv)
            if argv[:2] == ['container', 'inspect']:
                return '{"name": "nix-xd-arm-store"}'
            if "build" in argv:
                return fake_rootfs
            if "readlink" in argv:
                return "/nix/store/" + "b" * 32 + "-busybox/bin/busybox"
            if "sha256sum" in argv:
                return "c" * 64 + "  /nix/store/..."
            return ""
        with patch.object(shoal.Path, "is_file", return_value=True), \
             patch.object(shoal, "run", side_effect=fake_run), \
             patch.object(shoal, "endpoints", return_value=[("farcaster", 2222, Path("/tmp/known"))]), \
             patch.object(shoal, "ssh", return_value="SHOAL_GUEST_READER=passed\nSHOAL_GUEST_READER=passed\nSHOAL_GUEST_STORAGE=passed"):
            shoal.storage(args)
        self.assertEqual(calls[0][:3], ["container", "inspect", "nix-xd-arm"])
        self.assertTrue(any("storeProbeRootfs^out" in " ".join(c) for c in calls))

    def test_defaults_follow_generic_runtime_state_contract(self):
        repo = Path(__file__).resolve().parents[1]
        makefile = (repo / "Makefile").read_text()
        self.assertIn("podman system connection list", makefile)
        self.assertIn("GUEST_STATE_ROOT ?= $(HOME)/.local/state/nix-xd/coreos", makefile)
        self.assertIn("SHOAL_STATE_ROOT ?= $(GUEST_STATE_ROOT)", makefile)

    def test_missing_guest_credentials_fail_before_qualification(self):
        args = argparse.Namespace(ssh_key="/unavailable/key", owner="nix-xd-arm")
        with patch.object(shoal.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "Missing SSH key"):
                shoal.storage(args)


if __name__ == "__main__":
    unittest.main()
