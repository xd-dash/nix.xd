#!/usr/bin/env python3
"""Static ownership guard; intentionally does not inspect or change the Mac runtime."""
from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[1]
makefile = (root / "Makefile").read_text()
task = (root / "bin/nix-xd-task").read_text()
guest = (root / "bin/nix-xd-guest-app").read_text()
policy = (root / "docs/architecture-v20261115.md").read_text()

def check(condition, label):
    if not condition:
        raise SystemExit(f"NIX_XD_ARCHITECTURE_CHECK=failed reason={label}")

check("make run FLAKE=" in policy, "undocumented-flake-transport")
check("make guest-app" in policy, "undocumented-guest-transport")
check("make project-run" in policy, "undocumented-project-dispatch")
check("project-run:" in makefile, "missing-canonical-project-launcher")
check(len(re.findall(r"^project-run:", makefile, re.M)) == 1,
      "duplicate-project-run-target")
check("NIX_XD_PROJECT_RUNTIME_FLAKE=" in makefile, "missing-runtime-flake-binding")
check("NIX_XD_PROJECT_FLAKE=" in makefile, "missing-project-flake-binding")
check('inside nix run --no-write-lock-file "$NIX_XD_PROJECT_RUNTIME_FLAKE#project-launch"' in task,
      "project-launcher-not-inside-nix-alpine")
check("local/<application>/host-actions/<action>.sh" in policy,
      "missing-host-action-exception")
legacy_host_path = root / "mk/legacy-host-actions.mk"
host_path = root / "bin/nix-xd-project-host-run"
if legacy_host_path.exists():
    check("include mk/legacy-host-actions.mk" in makefile, "host-action-compatibility-not-isolated")
    check(host_path.exists(), "host-action-transport-missing")
    legacy_host = legacy_host_path.read_text()
    host = host_path.read_text()
    check("project-host-run:" in legacy_host, "untracked-host-action-entry")
    check("bin/nix-xd-project-host-run" in legacy_host, "host-action-source-drift")
    check('script="$source/local/$application/host-actions/$action.sh"' in host,
          "host-dispatch-contract-drift")
    check('[[ "$revision" =~ ^[a-f0-9]{40}$ ]]' in host, "host-action-missing-pin")
    check('[[ -z "$(git -C "$source" status --porcelain --untracked-files=no)" ]]' in host,
          "host-action-dirty-source-accepted")
else:
    check("include mk/legacy-host-actions.mk" not in makefile and not host_path.exists(),
          "orphaned-host-action-transport")
check('inside nix --option system "$system" run' in task,
      "nix-alpine-not-execution-authority")
check('inside nix --option system "$system" build' in task,
      "nix-alpine-not-build-authority")
check('owner cat "$output/guest.sh" | ssh -T' in guest,
      "guest-transport-not-pinned")
check('StrictHostKeyChecking=yes' in guest, "guest-host-key-not-verified")
check('GUEST_STATE_ROOT:-$HOME/.local/state/nix-xd/coreos' in guest,
      "guest-state-default-drift")
check("PROVIDER ?= podman" in makefile, "wrong-default-provider")
native_grants = json.loads((root / "examples/ghxd-native-grants.json").read_text())
check(native_grants.get("schema") == 1 and native_grants.get("scope") == "nix-xd-arm",
      "invalid-native-ghxd-grant-contract")
grants = native_grants.get("grants", [])
check({g.get("destination") for g in grants} == {
    "/run/nix-xd/mounts/ghxd-secret",
    "/run/nix-xd/mounts/ghxd-home",
    "/run/nix-xd/mounts/ghxd-workspaces",
}, "invalid-native-ghxd-grant-destinations")
check(all(g.get("reader") == "nix-xd-arm" and g.get("writer") == "nix-xd-arm"
          and g.get("access") == "rw" for g in grants),
      "native-ghxd-grants-must-have-one-writer")

# Retired application Make modules must not return through another opt-in flag.
for retired in ("legacy-shoal.mk", "legacy-vm-profiles.mk",
                "legacy-application-controllers.mk"):
    check(not (root / "mk" / retired).exists(), "retired-application-module-returned-" + retired)
    check(retired not in makefile, "retired-application-include-returned-" + retired)
for retired_test in ("shoal-contract.py", "shoal-runtime.py"):
    check(not (root / "tests" / retired_test).exists(), "retired-shoal-test-returned")
# Detect any newly added application-named command in the canonical interface.
# Historical Shoal is recorded above; do not silently expand this exception.
app_specific = {target for target in re.findall(r"^([a-z][a-z0-9-]*(?:shoal|fatline|probot|farcaster)[a-z0-9-]*):", makefile, re.M)}
check(not app_specific, "app-specific-nix-xd-target-in-canonical-makefile")
legacy_path = root / "mk/legacy-shoal.mk"
if legacy_path.exists():
    check("include mk/legacy-shoal.mk" in makefile, "historical-shoal-not-isolated")
    check("shoal-qualify:" in legacy_path.read_text(), "historical-shoal-target-drift")
else:
    check("include mk/legacy-shoal.mk" not in makefile, "orphaned-shoal-include")
# The current contract is normative for new work; historical compatibility
# adapters are not permission to add another entrypoint.
canonical = (root / "docs/CANONICAL-ARCHITECTURE.md").read_text()
agents = (root / "AGENTS.md").read_text()
for phrase in ("Forbidden new idioms", "One writer per Nix store domain",
               "Nix-Alpine pinned flake", "project-host-run", "full 40-character"):
    check(phrase in canonical, "canonical-contract-missing-" + phrase.replace(" ", "-"))
check("docs/CANONICAL-ARCHITECTURE.md" in agents, "agent-policy-not-linked")
check("DO NOT ADD" in agents and "quarantined exceptions" in agents,
      "agent-legacy-ban-not-explicit")
check("~/.local/nix.xd/logs" in canonical and "~/.local/state/nix-xd" in canonical,
      "state-or-log-policy-drift")
print("NIX_XD_ARCHITECTURE_CHECK=passed owner=nix-alpine host_exceptions=documented application_targets=legacy-only")
