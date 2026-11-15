#!/usr/bin/env python3
"""Static ownership guard; intentionally does not inspect or change the Mac runtime."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
makefile = (root / "Makefile").read_text()
task = (root / "bin/nix-xd-task").read_text()
guest = (root / "bin/nix-xd-guest-app").read_text()
host = (root / "bin/nix-xd-project-host-run").read_text()
policy = (root / "docs/architecture-v20261115.md").read_text()

def check(condition, label):
    if not condition:
        raise SystemExit(f"NIX_XD_ARCHITECTURE_CHECK=failed reason={label}")

check("make run FLAKE=" in policy, "undocumented-flake-transport")
check("make guest-app" in policy, "undocumented-guest-transport")
check("make project-run" in policy, "undocumented-project-dispatch")
check("local/<application>/host-actions/<action>.sh" in policy,
      "missing-host-action-exception")
check("project-host-run:" in makefile, "untracked-host-action-entry")
check("bin/nix-xd-project-host-run" in makefile, "host-action-source-drift")
check('script="$source/local/$application/host-actions/$action.sh"' in host,
      "host-dispatch-must-remain-project-owned")
check('[[ "$revision" =~ ^[a-f0-9]{40}$ ]]' in host, "host-action-missing-pin")
check('[[ -z "$(git -C "$source" status --porcelain --untracked-files=no)" ]]' in host,
      "host-action-dirty-source-accepted")
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

# Detect any newly added application-named command in the canonical interface.
# Historical Shoal is recorded above; do not silently expand this exception.
app_specific = {target for target in re.findall(r"^([a-z][a-z0-9-]*(?:shoal|fatline|probot|farcaster)[a-z0-9-]*):", makefile, re.M)}
check(app_specific <= {"shoal-qualify"}, "new-app-specific-nix-xd-target")
print("NIX_XD_ARCHITECTURE_CHECK=passed owner=nix-alpine host_exceptions=documented application_targets=legacy-only")
