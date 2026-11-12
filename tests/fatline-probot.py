#!/usr/bin/env python3
"""Static contract tests for real VM1 Probot artifact verification transport."""
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lib"))
import fatline_probot as module

class GuestStoreTests(unittest.TestCase):
    def test_exact_paths_and_no_secret_transport(self):
        pin=json.loads((ROOT/"examples/ghxd-agni-probot-guest-store.json").read_text())["sources"]["agni"]
        sha="b"*40
        entry=lambda name: {"revision":sha,"store":"/nix/store/"+"a"*32+"-"+name}
        artifact={"schema":1,"system":"aarch64-linux","ghxd_credentials_included":False,
                  "node":"/nix/store/"+"a"*32+"-nodejs/bin/node",
                  "artifacts":{"skymill":entry("skymill-http"),"logma":entry("logma-lifecycle"),
                               "probot-runtime":entry("probot")}}
        verifier="#!/usr/bin/env bash\necho 'AGNI_PROBOT_GUEST_STORE=passed roles=3 node=visible mount=9p-ro'\n"
        def owner(*argv):
            if argv[0]=="cat" and argv[1].endswith("/.nix-xd-source-revision"): return pin["revision"]
            if argv[0]=="cat" and argv[1].endswith("/artifacts.json"): return json.dumps(artifact)
            if argv[0]=="cat" and argv[1].endswith("/probot-guest-store.sh"): return verifier
            if argv[0]=="test": return ""
            raise AssertionError(argv)
        link=SimpleNamespace(state={"status":"prepared","boot":"boot-123"},profile="vm1",
             runtime=SimpleNamespace(owner=owner),command=["ssh","guest"],env={},
             retain=lambda:None)
        with patch.object(module,"run",return_value="AGNI_PROBOT_GUEST_STORE=passed roles=3 node=visible mount=9p-ro\n") as run:
            module.preflight(link,"/home/nixuser/.local/state/agni/probot-webhook/artifacts.json")
        script=run.call_args.args[3]
        self.assertIn("AGNI_PROBOT_GUEST_LOGMA_SHA",script)
        self.assertIn("set -Eeuo pipefail\nexport AGNI_PROBOT_GUEST_EXPECTED_BOOT=",script)
        self.assertNotIn(r"\nexport",script)
        self.assertIn(sha,script)
        self.assertNotIn("private_key",script)
        self.assertNotIn("oauth",script.lower())

    def test_recorded_vm1_selection_is_reused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            selection=root/".state/agni-coreos/vm1-selection.json"
            selection.parent.mkdir(parents=True)
            selection.write_text(json.dumps({"schema":1,"profile":"vm1",
                "agniRepository":"dash-xd/agni","agniRevision":"a"*40,
                "flake":"/workspaces/agni20261111/local/fatline"}))
            from unittest.mock import patch
            with patch.object(module, "REPO", root), patch.dict(module.os.environ,{},clear=True):
                module.selected_composition()
                self.assertEqual(module.os.environ["NIX_XD_COMPOSITION_REV"],"a"*40)
                self.assertEqual(module.os.environ["NIX_XD_COMPOSITION_FLAKE"],
                    "/workspaces/agni20261111/local/fatline")

    def test_partial_composition_selection_is_rejected(self):
        with patch.dict(module.os.environ,{"NIX_XD_COMPOSITION_REV":"a"*40},clear=True):
            with self.assertRaises(ValueError):
                module.selected_composition()

    def test_wrong_artifact_selection_fails_before_ssh(self):
        pin=json.loads((ROOT/"examples/ghxd-agni-probot-guest-store.json").read_text())["sources"]["agni"]
        def owner(*argv):
            if argv[0]=="cat" and argv[1].endswith("/.nix-xd-source-revision"):return pin["revision"]
            if argv[0]=="cat":return json.dumps({"schema":1,"system":"aarch64-linux",
                                                    "ghxd_credentials_included":False,"artifacts":{}})
            raise AssertionError(argv)
        link=SimpleNamespace(state={"status":"prepared","boot":"abc"},profile="vm1",
             runtime=SimpleNamespace(owner=owner))
        with self.assertRaises(ValueError):
            module.preflight(link,"/home/nixuser/.local/state/agni/probot-webhook/artifacts.json")

if __name__=="__main__":
    unittest.main()
