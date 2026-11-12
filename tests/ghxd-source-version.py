#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ghxd_version", ROOT / "lib/ghxd_source_version.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DatedSources(unittest.TestCase):
    def test_reject_feature_checkout_and_unpinned_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "manifest.json"
            entry = {"schema": 1, "sources": {
                "agni": {"repository": "dash-xd/agni",
                         "revision": "a" * 40, "checkout": "agni20261112"}}}
            def check(candidate, valid):
                root.write_text(json.dumps(candidate))
                if valid:
                    module.validate(root)
                else:
                    with self.assertRaises(ValueError):
                        module.validate(root)
            check(entry, True)
            entry["sources"]["agni"]["checkout"] = "agni-vm1-auth"
            check(entry, False)
            entry["sources"]["agni"]["checkout"] = "agni20260230"
            check(entry, False)
            entry["sources"]["agni"]["checkout"] = "agni20261112"
            entry["sources"]["agni"]["revision"] = "v20261112"
            check(entry, False)
            entry["sources"]["agni"]["revision"] = "a" * 40
            entry["sources"]["skymill"] = {
                "repository": "xd-dash/skymill", "revision": "b" * 40,
                "checkout": "skymill20261113"}
            check(entry, False)


if __name__ == "__main__":
    unittest.main()
