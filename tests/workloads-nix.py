#!/usr/bin/env python3
"""Real Nix integration on a disposable CI runner; no CoreOS VM required."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

assert os.environ.get("GITHUB_ACTIONS") == "true", "Run only on the disposable Actions runner"
assert os.getuid() == 0, "CI fixture requires a disposable root-owned Nix store"
repo = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controller", repo / "lib/workloads.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
revision = "1" * 40
fixture = Path("/workspaces/nix-xd-ci-fixture")
assert not fixture.exists()
fixture.mkdir(parents=True)
(fixture / ".nix-xd-source-revision").write_text(revision + "\n")
(fixture / "flake.nix").write_text(r'''
{
  outputs = { self }: let
    system = "x86_64-linux";
    dependency = builtins.toFile "workload-ci-dependency" "retained dependency";
    executable = builtins.derivation {
      name = "workload-ci-executable"; inherit system;
      builder = "/bin/sh";
      args = [ "-c" ''
        /bin/mkdir -p "$out/bin"
        printf '#!/bin/sh\necho Hello, world!\n' > "$out/bin/hello"
        /bin/chmod +x "$out/bin/hello"
        printf '%s\n' '${dependency}' > "$out/dependency"
      '' ];
    };
    rootfs = builtins.derivation {
      name = "workload-ci-rootfs"; inherit system;
      builder = "/bin/sh";
      args = [ "-c" ''
        /bin/mkdir -p "$out/bin"
        /bin/ln -s '${executable}/bin/hello' "$out/bin/sh"
      '' ];
    };
  in {
    packages.${system} = { inherit executable rootfs; };
    workloads.${system}.starwisp-probe = {
      version = 1; name = "starwisp-probe"; inherit system;
      outputs = { executable = "executable"; rootfs = "rootfs"; };
      rootfs = "rootfs";
      command = { output = "executable"; path = "bin/hello"; args = []; };
      capabilities = [ "store-9p-ro" "user-systemd" "rootless-podman" ];
      network = "none"; runtimeMaxSec = 30;
      qualification = { mode = "exit-success"; stdoutContains = "Hello, world!"; };
    };
  };
}
''')
os.environ["NIX_CONFIG"] = "experimental-features = nix-command flakes\nbuild-users-group =\nsandbox = false\nsubstituters =\n"
roots = Path("/nix/var/nix/gcroots/nix-xd/workload-ci")
assert not roots.exists()
try:
    with tempfile.TemporaryDirectory() as state:
        c = m.Controller(state, roots, repo / "bin/nix-xd-guest-store-exec")
        with c.locked("starwisp-probe"):
            prepared = c.prepare("starwisp-probe", "x86_64-linux", str(fixture), revision)
            generation = prepared["generation"]
            repeated = c.prepare("starwisp-probe", "x86_64-linux", str(fixture), revision)
            assert repeated["generation"] == generation
            manifest = prepared["manifest"]
            closure = manifest["outputs"]["executable"]["closure"]
            assert len(closure) >= 2, closure
            roots_output = subprocess.check_output(["nix-store", "--gc", "--print-roots"], text=True)
            for output in manifest["outputs"].values():
                assert output["path"] in roots_output
            c.lifecycle("begin-activate", "starwisp-probe", target="12345678-1234-1234-1234-123456789abc")
            c.lifecycle("begin-stop", "starwisp-probe", target="12345678-1234-1234-1234-123456789abc")
            assert (roots / "starwisp-probe" / generation).is_dir()
            c.lifecycle("confirm-stopped", "starwisp-probe", generation)
            assert not (roots / "starwisp-probe" / generation).exists()
            assert all(Path(p).exists() for p in closure)
            print("PASS: real Nix source pin, rooted builds, dependency closure, idempotent preparation and acknowledged release")
finally:
    shutil.rmtree(fixture)
    shutil.rmtree(roots, ignore_errors=True)
