#!/usr/bin/env python3
"""Check pinned Agni Probot artifacts through the existing CoreOS VM1 transport."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from compose_runtime import run
from compositions import require
from fatline_host_link import HostLink

REPO = Path(__file__).resolve().parents[1]
STORE = re.compile(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+")


def preflight(link, source_path):
    require(link.state, "Prepare existing Fatline VM1 host-link before Probot guest check")
    require(link.state.get("status") in ("prepared", "active"), "Existing host-link is not prepared")
    require(link.profile == "vm1", "Probot integration currently targets CoreOS VM1 only")
    owner = link.runtime.owner
    bootstrap = json.loads((REPO / "examples/ghxd-agni-probot-guest-store.json").read_text())
    pinned = bootstrap["sources"]["agni"]
    require(pinned["repository"] == "dash-xd/agni" and
            re.fullmatch(r"[a-f0-9]{40}", pinned["revision"]), "Invalid Agni guest store source pin")
    checkout = pinned["checkout"]
    require(re.fullmatch(r"[a-z][a-z0-9-]{1,63}", checkout), "Invalid Agni checkout")
    staged = owner("cat", f"/workspaces/{checkout}/.nix-xd-source-revision").strip()
    require(staged == pinned["revision"], "Selected guest store validator does not match pinned Agni SHA")
    app = json.loads(owner("cat", source_path))
    require(app["schema"] == 1 and app["system"] == "aarch64-linux", "Incorrect ARM64 artifact manifest")
    require(app["ghxd_credentials_included"] is False, "Application artifact must not include GHXD credentials")
    require(set(app["artifacts"]) == {"skymill","logma","probot-runtime"}, "Incomplete application selection")
    for item in app["artifacts"].values():
        require(STORE.fullmatch(item["store"]), "Invalid pinned Nix store path")
        require(re.fullmatch(r"[a-f0-9]{40}", item["revision"]), "Invalid application source SHA")
    require(re.fullmatch(STORE.pattern + r"/bin/node", app["node"]), "Invalid pinned Node runtime")
    source = owner("cat", f"/workspaces/{checkout}/local/fatline/coreos-services/probot-guest-store.sh")
    require(source.startswith("#!/usr/bin/env bash"), "Invalid guest verifier")
    link.retain()
    # Existing writer owns the roots. Verify their targets while the guest mount is checked.
    for item in app["artifacts"].values():
        owner("test", "-e", item["store"])
    owner("test", "-x", app["node"])
    guest_values = {
        "AGNI_PROBOT_GUEST_EXPECTED_BOOT": link.state["boot"],
        "AGNI_PROBOT_GUEST_SKYMILL": app["artifacts"]["skymill"]["store"],
        "AGNI_PROBOT_GUEST_SKYMILL_SHA": app["artifacts"]["skymill"]["revision"],
        "AGNI_PROBOT_GUEST_LOGMA": app["artifacts"]["logma"]["store"],
        "AGNI_PROBOT_GUEST_LOGMA_SHA": app["artifacts"]["logma"]["revision"],
        "AGNI_PROBOT_GUEST_PROBOT": app["artifacts"]["probot-runtime"]["store"],
        "AGNI_PROBOT_GUEST_PROBOT_SHA": app["artifacts"]["probot-runtime"]["revision"],
        "AGNI_PROBOT_GUEST_NODE": app["node"],
    }
    # The guest verifier uses only Bash and exact controller-validated paths.
    script = "set -Eeuo pipefail\n" + "".join(
        "export " + name + "=" + shlex.quote(value) + "\n"
        for name, value in guest_values.items()
    ) + source + "\n"
    output = run(link.command, link.env, True, script, timeout=120)
    print(output, end="", flush=True)
    require("AGNI_PROBOT_GUEST_STORE=passed roles=3 node=visible mount=9p-ro" in output.splitlines(),
            "Guest artifact verification missing; all owner roots retained")
    print("FATLINE_PROBOT_VM1_STORE=passed guest=existing roles=3 credentials=excluded")



def selected_composition():
    """Use only a previously recorded, immutable Agni VM1 selection."""
    revision = os.environ.get("NIX_XD_COMPOSITION_REV", "")
    flake = os.environ.get("NIX_XD_COMPOSITION_FLAKE", "")
    if revision and flake:
        return
    require(not revision and not flake,
            "Specify COMPOSITION_REV and COMPOSITION_FLAKE together")
    evidence = REPO / ".state/agni-coreos/vm1-selection.json"
    require(evidence.is_file(),
            "No recorded VM1 composition; select COMPOSITION_REV and COMPOSITION_FLAKE explicitly")
    record = json.loads(evidence.read_text())
    require(record.get("schema") == 1 and record.get("profile") == "vm1" and
            record.get("agniRepository") == "dash-xd/agni" and
            re.fullmatch(r"[a-f0-9]{40}", record.get("agniRevision","")) and
            re.fullmatch(r"/workspaces/[A-Za-z0-9_.-]+/local/fatline", record.get("flake","")),
            "Recorded VM1 composition selection is invalid")
    os.environ["NIX_XD_COMPOSITION_REV"] = record["agniRevision"]
    os.environ["NIX_XD_COMPOSITION_FLAKE"] = record["flake"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("store-check",))
    args = parser.parse_args()
    selected_composition()
    link = HostLink()
    with link.lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "store-check":
            source = os.environ.get("NIX_XD_PROBOT_ARTIFACT_MANIFEST", "")
            require(not source, "Custom owner paths require a separate declared grant")
            manifest = link.runtime.owner("sh", "-ec",
                'printf %s "$HOME/.local/state/agni/probot-webhook/artifacts.json"')
            preflight(link, manifest)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print("Fatline Probot VM1: " + str(error), file=sys.stderr)
        sys.exit(1)
