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
from compose_runtime import Runtime
from fatline_generations import active_root

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



class ExistingVM1Link:
    """Read existing host-link provenance without re-evaluating a moved Agni checkout."""

    def __init__(self):
        self.runtime = Runtime(os.environ)
        self.scope = os.environ.get("NIX_XD_FATLINE_SCOPE", "fatline-arm-vm1")
        self.profile = os.environ.get("NIX_XD_FATLINE_PROFILE", "vm1")
        require(self.profile == "vm1" and self.scope == "fatline-arm-vm1",
                "This artifact gate requires the existing CoreOS VM1 scope")
        self.control_root = REPO / ".state/fatline" / self.scope
        require(self.control_root.is_dir(), "Existing VM1 host-link state is absent")
        self.lock_path = self.control_root / "controller.lock"
        self.root = active_root(self.runtime.scope, self.profile, self.control_root)
        state_path = self.root / "state.json"
        require(state_path.is_file(), "Prepare existing VM1 host-link before artifact check")
        self.state = json.loads(state_path.read_text())
        plan = self.state.get("plan", {})
        composition = self.state.get("composition", {})
        require(plan.get("schema") == 1 and plan.get("scope") == self.scope and
                plan.get("system") == os.environ.get("NIX_XD_SYSTEM") == "aarch64-linux" and
                plan.get("storeDomain") == "common", "Recorded VM1 plan is incompatible")
        require(composition.get("schema") == 1 and composition.get("profile") == "vm1" and
                composition.get("agniRepository") == "dash-xd/agni" and
                re.fullmatch(r"[a-f0-9]{40}", composition.get("agniRevision", "")),
                "Recorded VM1 composition provenance is invalid")
        source = plan.get("sources", {}).get("agni", {})
        require(source.get("repository") == "dash-xd/agni" and
                re.fullmatch(r"[a-f0-9]{40}", source.get("revision", "")) and
                source["revision"] == self.state.get("agniRev"),
                "Recorded VM1 transport revision is inconsistent")
        require(plan.get("ingress") == {"transport": "ssh-tcp-nginx-unix",
                "hostPort": 16379, "guestProxyPort": 16379}, "VM1 ingress differs")
        require(self.state.get("status") in ("prepared", "active") and
                re.fullmatch(r"[0-9a-f-]{36}", self.state.get("boot", "")),
                "Existing VM1 host-link is not prepared with a boot identity")
        placement = plan.get("placement", {})
        require(placement.get("kind") == "coreos" and placement.get("sshPort") == 2222,
                "Recorded VM1 placement is incompatible")
        self.runtime.plan = {"placements": {"vm1": placement},
                             "workloads": {"transport": {"placement": "vm1"}}}
        self.command, self.env = self.runtime.transport_command("vm1", "transport")

    def retain(self):
        paths = self.state
        require(len(paths.get("roots", [])) == 2, "Unexpected VM1 host-link roots")
        for root, target in zip(paths["roots"], (paths["bundle"], paths["archive"])):
            self.runtime.owner("sh", "-ec",
                'test -e "$2"; if [ -L "$1" ]; then test "$(readlink "$1")" = "$2"; '
                'else nix-store --realise --add-root "$1" "$2" >/dev/null; fi',
                "retain", root, target)


def runtime_preflight(link):
    require(link.state and link.state.get("status") in ("prepared","active"),
            "Existing host-link must be prepared before VM1 runtime inventory")
    script = """set -Eeuo pipefail
test "$(cat /proc/sys/kernel/random/boot_id)" = BOOT_PLACEHOLDER
test "$(id -u)" != 0
test "$(podman info --format '{{.Host.Security.Rootless}}')" = true
base="$HOME/.local/state/nix-xd/fatline/fatline-arm-vm1"
apps="$base/services"
units="$HOME/.config/containers/systemd"
test -d "$base"
test -d "$apps"
test -f "$base/credentials/users.acl"
test -f "$base/config/redis.conf"
profile=absent
if test -f "$apps/profile/profile.env" && test -f "$apps/bootstrap-template.acl"; then
  profile=installed
fi
redis=inactive
if systemctl --user is-active --quiet fatline-arm-vm1-redis.service; then
  redis=active
fi
app_units=0
for role in logma skymill; do
  if test -f "$units/fatline-arm-vm1-$role.container"; then
    app_units=$((app_units+1))
  fi
done
user_names=$(awk '$1=="user" {print $2}' "$base/credentials/users.acl" | LC_ALL=C sort -u)
for name in default publisher subscriber; do
  grep -Fxq "$name" <<< "$user_names" || {
    echo "Missing existing host-link Redis identity: $name" >&2
    exit 1
  }
done
test "$(grep -Fc 'user default off' "$base/credentials/users.acl")" = 1
echo "AGNI_PROBOT_VM1_RUNTIME_INVENTORY=passed profile=$profile redis=$redis application_units=$app_units"
if test "$profile" = installed; then
  test -f "$base/credentials/runtime/users.acl"
  test -f "$apps/profile/manifest.json"
  echo 'AGNI_PROBOT_VM1_PROFILE=present bootstrap=managed'
else
  echo 'AGNI_PROBOT_VM1_PROFILE=absent bootstrap=legacy'
fi
"""
    script=script.replace("BOOT_PLACEHOLDER", shlex.quote(link.state["boot"]))
    output=run(link.command,link.env,True,script,timeout=120)
    print(output,end="",flush=True)
    require("AGNI_PROBOT_VM1_RUNTIME_INVENTORY=passed " in output and
            ("AGNI_PROBOT_VM1_PROFILE=present bootstrap=managed" in output or
             "AGNI_PROBOT_VM1_PROFILE=absent bootstrap=legacy" in output),
            "CoreOS VM1 runtime profile inventory incomplete")
    print("FATLINE_PROBOT_VM1_RUNTIME_PREFLIGHT=passed activation=blocked")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("store-check","runtime-preflight",))
    args = parser.parse_args()
    link = ExistingVM1Link()
    with link.lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "runtime-preflight":
            runtime_preflight(link)
        elif args.action == "store-check":
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
