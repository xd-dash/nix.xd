#!/usr/bin/env python3
"""Exercise immutable Agni plan selection without a live Nix owner."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from agni_coreos_plan import resolve

SHA = "a" * 40
STORE = "/nix/store/" + "b" * 32 + "-agni-coreos-vm1-plan.json"
FLAKE = "/workspaces/agni20261111/local/fatline"


class Stub:
    def __init__(self, actual=SHA):
        self.actual = actual
        self.calls = []
        self.lock = json.dumps({
            "nodes": {"root": {"inputs": {"nix-alpine-runtime": "nix-alpine-runtime"}},
                      "nix-alpine-runtime": {"locked": {"rev": "c" * 40}},
                      "nixpkgs": {"locked": {"rev": "2" * 40}}}
        })
        self.plan = json.dumps({
            "schema": 1, "system": "aarch64-linux", "scope": "fatline-arm-vm1",
            "sourceSelection": {"immutableRevisionRequired": True, "mutableBranchAllowed": False},
            "fullFatlineQualified": False,
            "componentRevisions": {"logma":"d" * 40,"skymill":"e" * 40,"ratelimiter":"f" * 40},
            "sources": {"agni": {"revision": SHA}},
            "services": {"revision": SHA},
            "servicesProbe": {"revision": SHA},
            "servicesRecovery": {"revision": SHA},
            "guestAdapter": {"revision": SHA},
            "startupProfile": {"revision": SHA},
            "bootstrap": {"revision": SHA}
        })

    def owner(self, *args):
        self.calls.append(args)
        if args[:2] == ("cat", FLAKE.removesuffix("/local/fatline") + "/.nix-xd-source-revision"):
            return self.actual
        if args[:2] == ("cat", FLAKE + "/flake.lock"):
            return self.lock
        if args[0] == "nix":
            return STORE
        if args[:2] == ("cat", STORE):
            return self.plan
        raise AssertionError(args)


class Selection(unittest.TestCase):
    def test_selected_revision_and_lock_are_bound_to_output(self):
        stub = Stub()
        plan, evidence = resolve(stub, "vm1", {
            "NIX_XD_COMPOSITION_FLAKE": FLAKE, "NIX_XD_COMPOSITION_REV": SHA,
            "NIX_XD_SYSTEM": "aarch64-linux"
        })
        self.assertEqual(plan["scope"], "fatline-arm-vm1")
        self.assertEqual(evidence["agniRevision"], SHA)
        self.assertEqual(evidence["planOutput"], STORE)
        self.assertEqual(evidence["planSha256"], hashlib.sha256(stub.plan.encode()).hexdigest())
        self.assertIn("--no-update-lock-file", stub.calls[2])

    def test_legacy_agni_variables_do_not_select_composition(self):
        stub = Stub()
        with self.assertRaisesRegex(ValueError, "NIX_XD_COMPOSITION_REV"):
            resolve(stub, "vm1", {
                "NIX_XD_AGNI_FLAKE": FLAKE, "NIX_XD_AGNI_REV": SHA,
                "NIX_XD_SYSTEM": "aarch64-linux"
            })
        self.assertEqual(stub.calls, [])

    def test_mismatched_staged_commit_fails_before_build(self):
        stub = Stub(actual="1" * 40)
        with self.assertRaisesRegex(ValueError, "Staged Agni revision differs"):
            resolve(stub, "vm1", {
                "NIX_XD_COMPOSITION_FLAKE": FLAKE, "NIX_XD_COMPOSITION_REV": SHA,
                "NIX_XD_SYSTEM": "aarch64-linux"
            })
        self.assertEqual(len(stub.calls), 1)

    def test_missing_lock_entry_is_rejected(self):
        stub = Stub()
        stub.lock = '{"nodes":{"root":{"inputs":{}}}}'
        with self.assertRaisesRegex(ValueError, "lock must pin"):
            resolve(stub, "vm1", {
                "NIX_XD_COMPOSITION_FLAKE": FLAKE, "NIX_XD_COMPOSITION_REV": SHA,
                "NIX_XD_SYSTEM": "aarch64-linux"
            })
        self.assertEqual(len(stub.calls), 2)


if __name__ == "__main__":
    unittest.main()
