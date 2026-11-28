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
actions = {p.stem for p in ghxd.glob("*.sh")}
require(not actions, "smoke-host-actions-restored")
require(not (smoke / "local/ghxd/host-operator.sh").exists(), "smoke-host-operator-restored")
require(not (repo / "bin/nix-xd-project-host-run").exists(), "nix-host-dispatch-restored")

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
require(found_agni <= allowed_agni, "agni-host-action-inventory-expanded")
found_smoke = {str(item.relative_to(smoke)) for item in smoke.glob("local/*/host-actions/*.sh")}
require(not found_smoke, "smoke-host-actions-restored")
agni_operations = agni / "local/fatline/operations"
require(not (agni_operations / "guest-migration.sh").exists(), "monolithic-guest-migration-restored")
active_sources = [agni / "local/fatline/Makefile", *agni_operations.glob("*.sh")]
host_caller = any("APPLICATION=ghxd ACTION=source-sync" in p.read_text() for p in active_sources)
require(not host_caller, "agni-legacy-ghxd-caller-restored")
require("host Podman operator" in (agni / "local/fatline/qualification/architecture-v20261115.md").read_text(),
        "missing-agni-exception")
require("transitional adapters" in (smoke / "docs/composition-contract-v20261115.md").read_text(),
        "missing-smoke-exception")

print(f"NIX_XD_ARCHITECTURE_AUDIT=passed canonical=nix-alpine legacy_ghxd_caller={str(host_caller).lower()}")
print(f"NIX_XD_ARCHITECTURE_LEGACY=observed smoke_actions={len(actions)} agni_actions={len(found_agni)}")
