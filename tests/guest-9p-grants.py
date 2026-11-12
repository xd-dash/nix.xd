#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import guest_9p_grants as grants


def parse(data):
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / "manifest.json"
        path.write_text(json.dumps(data))
        return grants.load(path)


def fixture():
    return {
        "schema": 1,
        "guest": "vm1",
        "exports": [{
            "volume": "nix-xd-state-control-fixture",
            "tag": "fixture",
            "access": "ro"
        }]
    }


class Guest9PGrants(unittest.TestCase):
    def test_valid_read_only_volume(self):
        self.assertEqual(parse(fixture())["guest"], "vm1")

    def test_reject_duplicate_and_unsafe_mounts(self):
        for entry in (
            {"volume": "outside"},
            {"tag": "nixstore"},
            {"tag": "../escaped"},
            {"access": "rw"},
        ):
            obj = fixture()
            obj["exports"][0].update(entry)
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                parse(obj)
        obj = fixture()
        obj["exports"].append(dict(obj["exports"][0]))
        with self.assertRaises(ValueError):
            parse(obj)

    @patch.object(grants.subprocess, "check_output")
    def test_preflight_requires_state_volume_labels(self, output):
        data = fixture()
        output.return_value = json.dumps({
            "io.nix-xd.state.version": "1",
            "io.nix-xd.state.kind": "control",
            "io.nix-xd.state.name": "fixture",
        })
        grants.preflight(data, "coreos-arm64")
        output.return_value = json.dumps({
            "io.nix-xd.state.version": "1",
            "io.nix-xd.state.kind": "secret",
            "io.nix-xd.state.name": "fixture",
        })
        with self.assertRaisesRegex(ValueError, "mismatched"):
            grants.preflight(data, "coreos-arm64")


if __name__ == "__main__":
    unittest.main()
