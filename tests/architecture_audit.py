#!/usr/bin/env python3
"""Read-only caller and host-action audit for architecture cutover."""
from pathlib import Path
import argparse
import re

parser = argparse.ArgumentParser()
parser.add_argument("--agni", type=Path, required=True)
parser.add_argument("--smoke", type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]

def require(value, reason):
    if not value:
        raise SystemExit(f"NIX_XD_ARCHITECTURE_AUDIT=failed reason={reason}")

for name, root in (("agni", args.agni), ("smoke", args.smoke)):
    require(root.is_dir(), f"missing-{name}")
    require((root / ".git").exists(), f"not-a-checkout-{name}")

agni = args.agni.resolve()
smoke = args.smoke.resolve()
ghxd = smoke / "local/ghxd/host-actions"
require(ghxd.is_dir(), "missing-transitional-smoke-adapter")
allowed = {"bootstrap", "auth-start", "auth-finish", "auth-refresh", "source-sync", "inventory", "provision"}
actions = {p.stem for p in ghxd.glob("*.sh")}
require(actions == allowed, "smoke-host-operation-inventory-changed")
require("source-sync" in actions, "missing-current-ghxd-caller")

# The old host dispatcher is an exception with known callers, not an
# extension point. Reject introduction of new project-owned host-actions.
# Baseline inventory of preexisting, noncanonical Agni host actions.
# Changes to this set must accompany an explicit retirement or migration review.
allowed_agni = {
    "local/fatline/host-actions/resource-qualify.sh",
    "local/shoal/host-actions/bind.sh",
    "local/shoal/host-actions/hostkey-enroll.sh",
    "local/shoal/host-actions/hostkey-plan.sh",
    "local/shoal/host-actions/network-backup-capture.sh",
    "local/shoal/host-actions/network-backup-preflight.sh",
    "local/shoal/host-actions/network-backup-verify.sh",
    "local/shoal/host-actions/network-migration-prepare.sh",
    "local/shoal/host-actions/network-powerdown-qmp.sh",
    "local/shoal/host-actions/network-preflight.sh",
    "local/shoal/host-actions/service-relay-probe.sh",
    "local/shoal/host-actions/storage.sh",
    "local/shoal/host-actions/world1-ignition.sh",
    "local/shoal/host-actions/world1-preflight.sh",
    "local/shoal/host-actions/world1-start.sh",
    "local/vm/host-actions/boot.sh",
    "local/vm/host-actions/build.sh",
    "local/vm/host-actions/ignition.sh",
    "local/vm/host-actions/preflight.sh",
    "local/vm/host-actions/reset-failed.sh",
    "local/vm/host-actions/stop.sh",
}
found_agni = {str(item.relative_to(agni)) for item in agni.glob("local/*/host-actions/*.sh")}
require(found_agni == allowed_agni, "agni-host-action-inventory-changed")
found_smoke = {str(item.relative_to(smoke)) for item in smoke.glob("local/*/host-actions/*.sh")}
require(found_smoke == {"local/ghxd/host-actions/" + name + ".sh" for name in allowed},
        "smoke-host-action-inventory-changed")

host_operator = (smoke / "local/ghxd/host-operator.sh").read_text()
agni_dispatch = (agni / "local/fatline/operations/guest-migration.sh").read_text()
nix_host = (repo / "bin/nix-xd-project-host-run").read_text()
require("PROJECT=smoke20261112 APPLICATION=ghxd ACTION=source-sync" in agni_dispatch,
        "unlisted-transitional-ghxd-caller")
require("local/$application/host-actions/$action.sh" in nix_host,
        "host-dispatch-contract-drift")
require('p=(podman --connection "$machine")' in host_operator,
        "host-adapter-missing-or-untracked")
require("host Podman operator" in (agni / "local/fatline/qualification/architecture-v20261115.md").read_text(),
        "missing-agni-exception")
require("transitional adapters" in (smoke / "docs/composition-contract-v20261115.md").read_text(),
        "missing-smoke-exception")

print("NIX_XD_ARCHITECTURE_AUDIT=passed exceptions=ghxd-host-only canonical=nix-alpine migration=pending")
print(f"NIX_XD_ARCHITECTURE_LEGACY=observed host_actions={len(actions)} owner=smoke/ghxd")
