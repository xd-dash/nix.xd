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

    def test_persisted_vm1_host_link_without_staging_composition(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_dir = root / ".state/fatline/fatline-arm-vm1"
            state_dir.mkdir(parents=True)
            state = {
                "status": "prepared",
                "boot": "11111111-1111-1111-1111-111111111111",
                "agniRev": "a"*40,
                "composition": {"schema":1,"profile":"vm1",
                    "agniRepository":"dash-xd/agni","agniRevision":"b"*40},
                "plan": {"schema":1,"scope":"fatline-arm-vm1",
                    "system":"aarch64-linux","storeDomain":"common",
                    "sources":{"agni":{"repository":"dash-xd/agni","revision":"a"*40}},
                    "ingress":{"transport":"ssh-tcp-nginx-unix",
                               "hostPort":16379,"guestProxyPort":16379},
                    "placement":{"kind":"coreos","container":"coreos-starwisp",
                                 "sshPort":2222}},
                "roots":["/nix/root1","/nix/root2"],"bundle":"/nix/store/bundle",
                "archive":"/nix/store/archive",
            }
            (state_dir/"state.json").write_text(json.dumps(state))
            fake=SimpleNamespace(scope="nix-xd-arm",
                plan=None, transport_command=lambda place,name: (["ssh","guest"],{}))
            with patch.object(module,"REPO",root), patch.object(module,"Runtime",return_value=fake), \
                 patch.object(module,"active_root",return_value=state_dir), \
                 patch.dict(module.os.environ,{"NIX_XD_SYSTEM":"aarch64-linux"},clear=True):
                link=module.ExistingVM1Link()
            self.assertEqual(link.state["agniRev"],"a"*40)
            self.assertEqual(link.command,["ssh","guest"])
            self.assertEqual(fake.plan["placements"]["vm1"]["sshPort"],2222)

    def test_missing_existing_vm1_state_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            fake=SimpleNamespace(scope="nix-xd-arm")
            with patch.object(module,"REPO",Path(temp)), \
                 patch.object(module,"Runtime",return_value=fake), \
                 patch.dict(module.os.environ,{"NIX_XD_SYSTEM":"aarch64-linux"},clear=True):
                with self.assertRaises(ValueError):
                    module.ExistingVM1Link()

    def test_vm1_runtime_inventory_uses_pinned_boot_and_does_not_print_secrets(self):
        link=SimpleNamespace(state={"status":"prepared","boot":"11111111-1111-1111-1111-111111111111"},
            command=["ssh","guest"],env={})
        output=("AGNI_PROBOT_VM1_RUNTIME_INVENTORY=passed profile=installed redis=active application_units=2\\n"
                "AGNI_PROBOT_VM1_PROFILE=present bootstrap=managed\\n")
        with patch.object(module,"run",return_value=output) as remote:
            module.runtime_preflight(link)
        script=remote.call_args.args[3]
        self.assertIn("11111111-1111-1111-1111-111111111111",script)
        self.assertIn("fatline-arm-vm1-redis.service",script)
        self.assertIn("user default off",script)
        self.assertNotIn("users.acl\")\n",script)
        self.assertNotIn("cat \"$base/credentials/users.acl\"",script)

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
