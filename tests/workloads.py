#!/usr/bin/env python3
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workload_controller", REPO / "lib/workloads.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
REVISION = "a" * 40
SOURCE = "/nix/store/" + "a" * 32 + "-source"
BOOT = "12345678-1234-1234-1234-123456789abc"
DECLARATION = {"version": 1, "name": "starwisp-probe", "system": "aarch64-linux",
               "outputs": {"rootfs": "storeProbeRootfs", "executable": "storeProbeDynamic"},
               "rootfs": "rootfs", "command": {"output": "executable", "path": "bin/hello",
               "args": ["a b", "$(touch /tmp/unsafe)", "quote'\nline"]},
               "qualification": {"mode": "exit-success", "stdoutContains": "Hello, world!"},
               "capabilities": m.CAPABILITIES, "network": "none", "runtimeMaxSec": 30}


class FakeController(m.Controller):
    def nix(self, *args):
        if args[:2] == ("flake", "metadata"):
            return json.dumps({"path": SOURCE, "locked": {"narHash": "sha256-test"}})
        if args[0] == "eval":
            return json.dumps(self.declaration)
        if args[0] == "build":
            root = Path(args[args.index("--out-link") + 1])
            path = "/nix/store/" + ("b" if root.name == "rootfs" else "c") * 32 + "-" + root.name
            if root.name == "rootfs" and self.declaration.get("rootfsFormat") == "alpine-archive":
                path += ".tar.gz"
            root.symlink_to(path)
            return path
        if args[0] == "path-info":
            return json.dumps({p: {} for p in [args[-1], "/nix/store/" + "d" * 32 + "-dependency"]})
        raise AssertionError(args)


class Lifecycle(unittest.TestCase):
    def context(self, manager):
        value = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return value

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.c = FakeController(base / "state", base / "roots", REPO / "bin/nix-xd-guest-store-exec")
        self.c.declaration = copy.deepcopy(DECLARATION)
        original_read = Path.read_text
        original_exists = Path.exists
        original_symlink = Path.is_symlink
        original_file = Path.is_file
        self.context(patch.object(Path, "is_file", lambda p:
            True if str(p).startswith("/nix/store/") and str(p).endswith(".tar.gz") else original_file(p)))
        self.context(patch.object(Path, "read_text", lambda p, *a, **kw:
            REVISION if p.name == ".nix-xd-source-revision" else original_read(p, *a, **kw)))
        self.context(patch.object(Path, "exists", lambda p:
            True if str(p).startswith("/nix/store/") else original_exists(p)))
        self.context(patch.object(Path, "is_symlink", lambda p:
            True if str(p).startswith("/nix/store/") and str(p).endswith("/bin/sh") else original_symlink(p)))
        self.context(patch.object(os, "access", return_value=True))
        def register(argv, **kw):
            self.assertEqual(argv[:3], ["nix-store", "--realise", "--add-root"])
            Path(argv[3]).symlink_to(argv[4])
        self.context(patch.object(m.subprocess, "run", side_effect=register))

    def prepare(self):
        with self.c.locked("starwisp-probe"):
            return self.c.prepare("starwisp-probe", self.c.declaration["system"], "/workspaces/nix.xd", REVISION)["generation"]

    def lifecycle(self, action, gen=None, target=None):
        with self.c.locked("starwisp-probe"):
            return self.c.lifecycle(action, "starwisp-probe", gen, target)

    def test_prepare_is_idempotent_and_pins_closures(self):
        gen = self.prepare()
        self.assertEqual(gen, self.prepare())
        entry = self.c.load("starwisp-probe")["generations"][gen]
        self.assertEqual(entry["manifest"]["source"]["revision"], REVISION)
        self.assertIn("source", entry["manifest"]["outputs"])
        self.assertTrue((self.c.roots / "starwisp-probe" / gen / "rootfs").is_symlink())
        self.assertIn("dependency", entry["manifest"]["outputs"]["rootfs"]["closure"][1])

    def test_failed_or_uncertain_activation_keeps_roots(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.assertEqual(self.c.load("starwisp-probe")["active"], gen)
        self.assertTrue((self.c.roots / "starwisp-probe" / gen).is_dir())
        with self.assertRaisesRegex(ValueError, "stop intent"):
            self.lifecycle("confirm-stopped", gen)
        with self.assertRaisesRegex(ValueError, "boot identity changed"):
            self.lifecycle("begin-stop", target="87654321-1234-1234-1234-123456789abc")
        self.assertTrue((self.c.roots / "starwisp-probe" / gen).is_dir())

    def test_upgrade_preserves_previous_until_confirmed_stop(self):
        old = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("confirm-active", old)
        self.c.declaration["command"]["args"] = ["new-generation"]
        new = self.prepare()
        self.assertNotEqual(old, new)
        with self.assertRaisesRegex(ValueError, "Stop the active"):
            self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("begin-stop", target=BOOT)
        self.assertTrue((self.c.roots / "starwisp-probe" / old).is_dir())
        self.lifecycle("confirm-stopped", old)
        self.assertFalse((self.c.roots / "starwisp-probe" / old).exists())
        self.assertTrue((self.c.roots / "starwisp-probe" / new).is_dir())
        self.lifecycle("begin-activate", target=BOOT)
        self.assertEqual(self.c.load("starwisp-probe")["active"], new)

    def test_reprepare_stopped_generation_has_fresh_identity(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("begin-stop", target=BOOT)
        self.lifecycle("confirm-stopped", gen)
        retry = self.prepare()
        self.assertNotEqual(retry, gen)
        self.assertEqual(retry, self.prepare())

    def test_alpine_archive_uses_same_generation_lifecycle(self):
        self.c.declaration["rootfsFormat"] = "alpine-archive"
        gen = self.prepare()
        manifest = self.c.load("starwisp-probe")["generations"][gen]["manifest"]
        self.assertIsNone(manifest["shell"])
        self.assertTrue(manifest["rootfsArchive"].endswith(".tar.gz"))
        self.lifecycle("begin-activate", target=BOOT)
        script = self.c.guest_script("activate", "starwisp-probe", gen)
        self.assertIn("--rootfs-archive " + manifest["rootfsArchive"], script)
        self.lifecycle("begin-stop", target=BOOT)
        self.lifecycle("confirm-stopped", gen)
        self.assertFalse((self.c.roots / "starwisp-probe" / gen).exists())

    def test_running_environment_retains_roots_and_exposes_service_operations(self):
        self.c.declaration["rootfsFormat"] = "alpine-archive"
        self.c.declaration["runtimeMaxSec"] = 0
        self.c.declaration["qualification"] = {"mode": "running", "command":
            {"output": "executable", "path": "bin/ready", "args": []},
            "stdoutContains": "READY", "timeoutSec": 120}
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        activation = self.c.guest_script("activate", "starwisp-probe", gen)
        self.assertIn("RuntimeMaxSec=infinity", activation)
        self.lifecycle("confirm-active", gen)
        for operation in ("status", "check", "shell"):
            script = self.c.guest_script(operation, "starwisp-probe", gen)
            process = subprocess.Popen(["bash", "-n"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, error = process.communicate(script)
            self.assertEqual(process.returncode, 0, error)
        shell = self.c.guest_script("shell", "starwisp-probe", gen)
        self.assertLess(shell.index("flock -u 9"), shell.index("exec podman exec -it"))
        summary = self.lifecycle("summary")
        self.assertTrue(summary["rootsRetained"])
        self.assertEqual(summary["status"], "active")
        self.assertEqual(self.lifecycle("mode"), "running")
        self.lifecycle("begin-stop", target=BOOT)
        self.assertTrue((self.c.roots / "starwisp-probe" / gen).is_dir())
        self.lifecycle("confirm-stopped", gen)
        self.assertFalse(self.lifecycle("summary")["rootsRetained"])

    def running_generation(self):
        self.c.declaration["rootfsFormat"] = "alpine-archive"
        self.c.declaration["runtimeMaxSec"] = 0
        self.c.declaration["qualification"] = {"mode": "running", "command":
            {"output": "executable", "path": "bin/ready", "args": []},
            "stdoutContains": "READY", "timeoutSec": 120}
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("confirm-active", gen)
        return gen

    def recreate(self, action, gen, transaction=None, evidence=None, target=None):
        with self.c.locked("starwisp-probe"):
            return self.c.recreation(action, "starwisp-probe", gen, target, transaction, evidence)

    def snapshot(self, gen, transaction, after=False, **overrides):
        entry = self.c.load("starwisp-probe")["generations"][gen]
        values = {"GENERATION": gen, "BOOT_ID": BOOT, "TRANSACTION": transaction,
            "INSTANCE": entry.get("instance") or "legacy", "CONTAINER_ID": ("b" if after else "a") * 64,
            "NIX_PATH": "/nix/store/" + "n" * 32 + "-nix/bin/nix",
            "HELLO_PATH": "/nix/store/" + "h" * 32 + "-hello", "NIX_VERSION": "nix 2.34.9",
            "METADATA_QUERY": "passed", "WRITABLE_STATE": "fresh" if after else "marked"}
        values.update(overrides)
        return "\n".join("RECREATE_" + key + "=" + value for key, value in values.items())

    def test_recreation_retains_generation_roots_through_all_phases(self):
        gen = self.running_generation()
        roots = self.c.roots / "starwisp-probe" / gen
        links = {p.name: os.readlink(p) for p in roots.iterdir()}
        tx = self.recreate("begin-recreate", gen, target=BOOT)
        self.assertEqual(self.recreate("begin-recreate", gen, target=BOOT), tx)
        self.assertEqual(self.recreate("recreate-phase", gen, tx), "snapshot")
        before = self.snapshot(gen, tx)
        self.recreate("recreate-record-before", gen, tx, before)
        old_stop = self.c.guest_script("recreate-stop", "starwisp-probe", gen)
        self.assertNotIn('rm -rf -- "$run_dir"', old_stop)
        with self.assertRaises(ValueError):
            self.lifecycle("begin-stop", target=BOOT)
        for action in ("recreate-stopped", "recreate-activated", "recreate-checked"):
            self.recreate(action, gen, tx)
            self.assertEqual({p.name: os.readlink(p) for p in roots.iterdir()}, links)
        self.recreate("recreate-record-after", gen, tx, self.snapshot(gen, tx, after=True))
        self.recreate("confirm-recreated", gen, tx)
        self.assertEqual(self.c.load("starwisp-probe")["active"], gen)
        self.assertEqual(self.lifecycle("summary")["status"], "active")
        self.assertEqual(self.lifecycle("summary")["recreation"]["result"], "passed")
        instance = self.c.load("starwisp-probe")["generations"][gen]["instance"]
        self.assertEqual(self.lifecycle("runtime-path", gen), "starwisp-probe/" + gen + "/" + instance)
        self.assertIn(instance, self.c.guest_script("shell", "starwisp-probe", gen))
        # A later recreation has a new instance identity but retains the same content generation.
        tx2 = self.recreate("begin-recreate", gen, target=BOOT)
        self.assertNotEqual(tx, tx2)
        self.assertEqual({p.name: os.readlink(p) for p in roots.iterdir()}, links)

    def test_recreation_errors_and_abandonment_do_not_release_roots_early(self):
        gen = self.running_generation()
        with self.assertRaisesRegex(ValueError, "boot identity"):
            self.recreate("begin-recreate", gen, target="different")
        tx = self.recreate("begin-recreate", gen, target=BOOT)
        with self.assertRaises(ValueError):
            self.recreate("recreate-record-before", gen, tx, self.snapshot(gen, tx, BOOT_ID="different"))
        with self.assertRaises(ValueError):
            self.recreate("recreate-stopped", gen, "f" * 32)
        self.assertTrue(self.lifecycle("summary")["rootsRetained"])
        self.recreate("abandon-recreate", gen, tx)
        self.assertTrue(self.lifecycle("summary")["rootsRetained"])
        self.c.guest_script("stop", "starwisp-probe", gen)
        self.lifecycle("confirm-stopped", gen)
        self.assertFalse(self.lifecycle("summary")["rootsRetained"])

    def test_recreation_verifies_new_container_and_unchanged_store_paths(self):
        gen = self.running_generation()
        tx = self.recreate("begin-recreate", gen, target=BOOT)
        self.recreate("recreate-record-before", gen, tx, self.snapshot(gen, tx))
        self.recreate("recreate-stopped", gen, tx)
        for operation in ("recreate-activate",):
            script = self.c.guest_script(operation, "starwisp-probe", gen)
            process = subprocess.Popen(["bash", "-n"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, error = process.communicate(script)
            self.assertEqual(process.returncode, 0, error)
        self.recreate("recreate-activated", gen, tx)
        self.c.guest_script("recreate-check", "starwisp-probe", gen)
        self.recreate("recreate-checked", gen, tx)
        for operation in ("snapshot-after", "status"):
            script = self.c.guest_script(operation, "starwisp-probe", gen)
            process = subprocess.Popen(["bash", "-n"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, error = process.communicate(script)
            self.assertEqual(process.returncode, 0, error)
        self.recreate("recreate-record-after", gen, tx,
                      self.snapshot(gen, tx, after=True, CONTAINER_ID="a" * 64))
        with self.assertRaisesRegex(ValueError, "not replaced"):
            self.recreate("confirm-recreated", gen, tx)
        self.assertTrue(self.lifecycle("summary")["rootsRetained"])

    def test_executor_update_blocks_activation_but_allows_safe_stop(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        replacement = Path(self.temp.name) / "new-executor"
        replacement.write_text("changed executor")
        self.c.executor = replacement
        with self.assertRaisesRegex(ValueError, "Executor changed"):
            self.c.guest_script("activate", "starwisp-probe", gen)
        self.lifecycle("begin-stop", target=BOOT)
        script = self.c.guest_script("stop", "starwisp-probe", gen)
        self.assertIn("WORKLOAD_STOPPED", script)
        self.assertTrue((self.c.roots / "starwisp-probe" / gen).is_dir())
        self.lifecycle("confirm-stopped", gen)
        self.assertFalse((self.c.roots / "starwisp-probe" / gen).exists())

    def test_host_binding_is_explicit_and_read_only(self):
        self.c.declaration["placement"] = "host"
        self.c.declaration["capabilities"] = ["store-bind-ro", "user-systemd", "rootless-podman"]
        gen = self.prepare()
        with self.assertRaisesRegex(ValueError, "host store export"):
            self.lifecycle("begin-activate", target=BOOT)
        self.c.lifecycle("begin-activate", "starwisp-probe", target=BOOT, store_export="/host-volume/store")
        script = self.c.guest_script("activate", "starwisp-probe", gen)
        self.assertIn("NIX_XD_STORE_TRANSPORT=bind", script)
        self.assertIn("/host-volume/store", script)
        self.assertNotIn("findmnt -rn --mountpoint /var/mnt/nixstore", script)

    def test_isolation_script_is_quoted_and_retains_roots(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("confirm-active", gen)
        for mode in ("write", "check"):
            script = self.c.guest_script("isolation", "starwisp-probe", gen, "f" * 32, mode)
            # setUp intercepts subprocess.run for native root registration.
            result = subprocess.Popen(["bash", "-n"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, error = result.communicate(script)
            self.assertEqual(result.returncode, 0, error)
            self.assertIn("ISOLATION_PID_NAMESPACE", script)
            self.assertIn("/nix/var/nix", script)
        with self.assertRaisesRegex(ValueError, "Invalid isolation"):
            self.c.guest_script("isolation", "starwisp-probe", gen, "unsafe", "write")
        self.assertTrue((self.c.roots / "starwisp-probe" / gen).is_dir())

    def test_reprepare_active_generation_preserves_instance(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("confirm-active", gen)
        state = self.c.load("starwisp-probe")
        state["generations"][gen]["instance"] = "f" * 32
        m.save(self.c.path("starwisp-probe"), state)
        self.assertEqual(self.prepare(), gen)
        self.assertEqual(self.c.load("starwisp-probe")["generations"][gen]["instance"], "f" * 32)

    def test_batch_retains_roots_and_matches_single_reader_script(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        self.lifecycle("confirm-active", gen)
        request = {"name": "starwisp-probe", "action": "isolation", "token": "f" * 32, "mode": "check"}
        result = self.c.batch([request])["starwisp-probe"]
        self.assertEqual(result["generation"], gen)
        self.assertEqual(result["script"], self.c.guest_script("isolation", "starwisp-probe", gen, "f" * 32, "check"))
        self.assertEqual(result["fingerprint"], self.lifecycle("assert-retained"))
        with self.assertRaisesRegex(ValueError, "batch names"):
            self.c.batch([request, request])
        with self.assertRaisesRegex(ValueError, "Unsupported batch action"):
            self.c.batch([dict(request, action="confirm-stopped")])

    def test_same_contract_for_both_systems(self):
        for system in ("aarch64-linux", "x86_64-linux"):
            self.c.declaration["system"] = system
            gen = self.prepare()
            self.assertEqual(self.c.load("starwisp-probe")["generations"][gen]["manifest"]["system"], system)

    def test_invalid_contracts_fail_before_builds(self):
        for field, value in [("capabilities", ["unknown"]), ("system", "aarch64-darwin"), ("runtimeMaxSec", 0)]:
            declaration = copy.deepcopy(DECLARATION)
            declaration[field] = value
            with self.assertRaises(ValueError):
                self.c.validate(declaration, "starwisp-probe", "aarch64-linux")
        with self.assertRaises(ValueError):
            self.c.prepare("starwisp-probe", "aarch64-linux", "/workspaces/nix.xd", "b" * 40)

    def test_guest_scripts_are_quoted_and_serialize_stop(self):
        gen = self.prepare()
        self.lifecycle("begin-activate", target=BOOT)
        activate = self.c.guest_script("activate", "starwisp-probe", gen)
        self.lifecycle("confirm-active", gen)
        check = self.c.guest_script("check", "starwisp-probe", gen)
        self.lifecycle("begin-stop", target=BOOT)
        stop = self.c.guest_script("stop", "starwisp-probe", gen)
        # Use the real subprocess module: the registration mock is scoped to m.subprocess.run.
        for script in (activate, check, stop):
            process = subprocess.Popen(["bash", "-n"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, error = process.communicate(script)
            self.assertEqual(process.returncode, 0, error)
            self.assertIn("flock -x 9", script)
        self.assertIn("'$(touch /tmp/unsafe)'", activate)
        self.assertIn('test ! -e "$tombstone"', activate)
        self.assertLess(stop.index('touch "$tombstone"'), stop.index('systemctl --user stop'))


if __name__ == "__main__":
    unittest.main()
