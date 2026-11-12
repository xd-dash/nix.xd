#!/usr/bin/env python3
"""Resolve an immutable Agni CoreOS plan through the Nix-Alpine owner."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from compose_runtime import Runtime, REPO, write_json
from compositions import require

STORE_PATH = re.compile(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+")
SHA = re.compile(r"[0-9a-f]{40}")


def resolve(runtime, profile, env=None):
    env = os.environ if env is None else env
    require(profile in ("vm1", "vm2"), "Select vm1 or vm2")
    flake = env.get("NIX_XD_COMPOSITION_FLAKE", "")
    revision = env.get("NIX_XD_COMPOSITION_REV", "")
    require(SHA.fullmatch(revision), "Pin NIX_XD_COMPOSITION_REV to the selected composition commit")
    require(re.fullmatch(r"/workspaces/[A-Za-z0-9_.-]+/local/fatline", flake),
            "NIX_XD_COMPOSITION_FLAKE must select a staged Fatline composition checkout")
    checkout = flake.removesuffix("/local/fatline")
    staged = runtime.owner("cat", checkout + "/.nix-xd-source-revision")
    require(staged == revision, "Staged Agni revision differs from the selected immutable commit")
    lock_raw = runtime.owner("cat", flake + "/flake.lock")
    lock = json.loads(lock_raw)
    require(lock["nodes"]["root"]["inputs"].get("nix-alpine-runtime") == "nix-alpine-runtime",
            "Agni lock must pin nix-alpine-runtime")
    require(SHA.fullmatch(lock["nodes"]["nix-alpine-runtime"]["locked"]["rev"]) and
            SHA.fullmatch(lock["nodes"]["nixpkgs"]["locked"]["rev"]),
            "Agni lock contains an invalid runtime or nixpkgs revision")
    output = runtime.owner("nix", "build", "--no-update-lock-file", "--no-write-lock-file",
                           "--print-out-paths", "--no-link", flake + "#coreos-plan-" + profile)
    require(STORE_PATH.fullmatch(output), "Invalid Agni plan store output")
    raw = runtime.owner("cat", output)
    plan = json.loads(raw)
    require(plan["schema"] == 1 and plan["system"] == env["NIX_XD_SYSTEM"] and
            plan["scope"] == "fatline-arm-" + profile and
            plan["sourceSelection"]["immutableRevisionRequired"] and
            not plan["sourceSelection"]["mutableBranchAllowed"], "Invalid Agni machine plan binding")
    manifest = {
        "schema": 1,
        "agniRepository": "dash-xd/agni",
        "agniRevision": revision,
        "flake": flake,
        "system": env["NIX_XD_SYSTEM"],
        "profile": profile,
        "planOutput": output,
        "planSha256": hashlib.sha256(raw.encode()).hexdigest(),
        "flakeLockSha256": hashlib.sha256(lock_raw.encode()).hexdigest(),
        "nixAlpineRevision": lock["nodes"]["nix-alpine-runtime"]["locked"]["rev"],
        "nixpkgsRevision": lock["nodes"]["nixpkgs"]["locked"]["rev"],
        "componentRevisions": plan["componentRevisions"],
        "components": {
            "transport": plan["sources"]["agni"]["revision"],
            "services": plan["services"]["revision"],
            "probe": plan["servicesProbe"]["revision"],
            "recovery": plan["servicesRecovery"]["revision"],
            "adapter": plan["guestAdapter"]["revision"],
            "startup": plan["startupProfile"]["revision"],
            "bootstrap": plan["bootstrap"]["revision"],
        },
    }
    return plan, manifest


def main():
    profile = os.environ.get("NIX_XD_FATLINE_PROFILE", "vm1")
    runtime = Runtime(os.environ)
    plan, manifest = resolve(runtime, profile)
    path = REPO / ".state/agni-coreos" / (profile + "-selection.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, manifest)
    print("AGNI_COREOS_PLAN_RESULT=passed profile=" + profile)
    print("AGNI_COREOS_PLAN_OUTPUT=" + manifest["planOutput"])
    print("AGNI_COREOS_SOURCE_REV=" + manifest["agniRevision"])
    print("AGNI_COREOS_PLAN_SHA256=" + manifest["planSha256"])
    print("AGNI_COREOS_EVIDENCE=" + str(path))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        print("Agni CoreOS plan error: " + str(error), file=sys.stderr)
        sys.exit(1)
