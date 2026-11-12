#!/usr/bin/env python3
"""Exercise state grant composition and live-mount verification without Podman."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import runtime_grants as grants

SCOPE = "nix-xd-arm"
VOLUME = "nix-xd-state-application-fixture"
DEST = "/run/nix-xd/mounts/input"


def fixture(access="ro"):
    return {
        "schema": 1,
        "scope": SCOPE,
        "grants": [{
            "volume": VOLUME,
            "destination": DEST,
            "access": access,
            "reader": SCOPE,
            "writer": SCOPE if access == "rw" else "operator"
        }]
    }


def parse(record):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "grant.json"
        path.write_text(json.dumps(record))
        return grants.load(path)


class GrantContracts(unittest.TestCase):
    def test_explicit_read_only_grant_renders_existing_quadlet_syntax(self):
        selected = parse(fixture())
        self.assertEqual(grants.mounts(selected), VOLUME + ":" + DEST + ":ro")

    def test_writable_grant_is_owner_bound(self):
        selected = parse(fixture("rw"))
        self.assertEqual(grants.mounts(selected), VOLUME + ":" + DEST + ":rw")
        record = fixture("rw")
        record["grants"][0]["writer"] = "other"
        with self.assertRaisesRegex(ValueError, "Only declared writer"):
            parse(record)

    def test_secret_volume_uses_same_mount_contract(self):
        record = fixture()
        record["grants"][0]["volume"] = "nix-xd-state-secret-qualification"
        record["grants"][0]["writer"] = "secrets-owner"
        selected = parse(record)
        self.assertEqual(grants.mounts(selected),
                         "nix-xd-state-secret-qualification:" + DEST + ":ro")
        record["grants"][0]["access"] = "rw"
        with self.assertRaisesRegex(ValueError, "Secret volume writable only"):
            parse(record)
        record["grants"][0]["writer"] = SCOPE
        self.assertEqual(grants.mounts(parse(record)),
                         "nix-xd-state-secret-qualification:" + DEST + ":rw")

    def test_rejects_ambiguous_and_unsafe_grants(self):
        for changed in (
            {"volume": "foreign-tenant-private"},
            {"destination": "/nix/store"},
            {"access": "invalid"},
            {"reader": "another-runtime"},
        ):
            record = fixture()
            record["grants"][0].update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse(record)
        record = fixture()
        record["grants"].append(dict(record["grants"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate grant destination"):
            parse(record)

    @patch.object(grants.subprocess, "run")
    @patch.object(grants.subprocess, "check_output")
    def test_live_inspection_requires_matching_volume_and_readability(self, output, run):
        mount = {"Type": "volume", "Name": VOLUME, "Destination": DEST, "RW": False}
        container = {"Id": "a" * 64, "Mounts": [mount]}
        labels = {
            "io.nix-xd.state.version": "1",
            "io.nix-xd.state.kind": "application",
            "io.nix-xd.state.name": "fixture"
        }
        output.side_effect = [json.dumps([container]), json.dumps(labels)]
        grants.verify(parse(fixture()), "coreos-arm64", SCOPE)
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[-4:], [SCOPE, "test", "-r", DEST])
        run.reset_mock()
        output.reset_mock()
        container["Mounts"][0]["RW"] = True
        output.side_effect = [json.dumps([container]), json.dumps(labels)]
        with self.assertRaisesRegex(ValueError, "Active runtime mount"):
            grants.verify(parse(fixture()), "coreos-arm64", SCOPE)
        run.assert_not_called()

    @patch.object(grants.subprocess, "run")
    @patch.object(grants.subprocess, "check_output")
    def test_competing_writable_writer_is_rejected(self, output, run):
        own_id = "a" * 64
        peer_id = "b" * 64
        own = {"Id": own_id, "Mounts": [{
            "Type": "volume", "Name": VOLUME, "Destination": DEST, "RW": True
        }]}
        labels = {
            "io.nix-xd.state.version": "1",
            "io.nix-xd.state.kind": "application",
            "io.nix-xd.state.name": "fixture"
        }
        peer = {"Id": peer_id, "Mounts": [{
            "Type": "volume", "Name": VOLUME, "Destination": "/other", "RW": True
        }]}
        output.side_effect = [json.dumps([own]), json.dumps(labels), peer_id, json.dumps([peer])]
        with self.assertRaisesRegex(ValueError, "Another container"):
            grants.verify(parse(fixture("rw")), "coreos-arm64", SCOPE)


if __name__ == "__main__":
    unittest.main()
