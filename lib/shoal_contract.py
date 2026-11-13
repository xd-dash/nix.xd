#!/usr/bin/env python3
"""Validate declared Shoal placement, 9P boundaries and pending proxy gates."""
import argparse
import json
from pathlib import Path

from compositions import require, validate

ALL_WORLDS = tuple("world" + str(n) for n in range(1, 8))
ROLES = ("redis", "nginx", "logma", "skymill", "squid")


def check(plan, worlds):
    validate(plan)
    require(plan["name"] == "shoal", "Expected Shoal composition")
    require(type(worlds) is int and 0 <= worlds <= 7, "Invalid World count")
    topology = plan.get("topology", {})
    require(topology.get("name") == "shoal" and topology.get("region") == "regional",
            "Invalid regional Shoal identity")
    require(topology.get("addressFamilies") == ["ipv4", "ipv6"],
            "Shoal must declare both address families")
    require(topology.get("farcaster") == "farcaster", "Missing Farcaster gateway")
    require(topology.get("members") == ["farcaster", *ALL_WORLDS] and
            topology.get("maxWorlds") == 7, "Shoal must contain one Farcaster and seven Worlds")
    guests = ["farcaster", *ALL_WORLDS[:worlds]]
    require(topology.get("active") == guests, "Selected Shoal members differ")
    require(set(plan["placements"]) == {"host", *guests}, "Unexpected guest placements")
    require(topology.get("service", {}).get("owner") == "agni" and
            topology["service"].get("farcasterRoles") == list(ROLES) and
            topology["service"].get("client") == "logmash",
            "Application contract is not owned by Agni/Smoke")
    egress = topology.get("egress", {})
    require(egress.get("gateway") == "farcaster" and
            egress.get("proxy") == "squid" and
            egress.get("protocol") == "http-connect" and
            egress.get("directWorldEgress") == "deny" and
            egress.get("qualified") is False,
            "Shoal internet policy must remain fail closed and unqualified")
    storage = topology.get("storage", {})
    require(storage == {
        "owner": "host", "common": "read-only-9p",
        "guestContainers": "read-only-bind-from-9p",
        "guestLocal": "guest-owned", "crossVmWritableStore": False,
    }, "Shoal store ownership is not qualified 9P topology")
    common = plan["domains"]["common"]
    require(common["owner"] == {"placement": "host", "scopeStore": True} and
            common["readers"] == ["host", *guests] and
            common["provisioning"] == "existing-host-store",
            "Shared Nix store must remain host-owned")
    require(set(plan["domains"]) == {"common", *(guest + "-local" for guest in guests)},
            "Guest-local stores cannot bleed between Worlds")
    for guest in guests:
        placement = plan["placements"][guest]
        require(placement["kind"] == "coreos" and placement["transport"] == "9p",
                "CoreOS store must use 9P")
        require(plan["domains"][guest + "-local"]["owner"]["placement"] == guest and
                plan["domains"][guest + "-local"]["readers"] == [guest],
                "Guest-local Nix store must remain guest-scoped")
    require(set(plan["workloads"]) == {"host-a", "host-b", *(guest + suffix for guest in guests for suffix in ("-a", "-b"))},
            "Every active placement needs two independent containers")
    for guest in guests:
        for suffix in ("-a", "-b"):
            workload = plan["workloads"][guest + suffix]
            require(workload == {"placement": guest, "domain": "common", "access": "read-only"},
                    "Guest container must read host Nix store read-only")
    return {"shoal": "declared", "members": len(guests), "worlds": worlds,
            "store": "host-owned-9p-read-only", "internet": "unqualified"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--worlds", required=True, type=int)
    args = parser.parse_args()
    result = check(json.loads(Path(args.input).read_text()), args.worlds)
    print("NIX_XD_SHOAL_CONTRACT=passed " + " ".join(
        key + "=" + str(value) for key, value in result.items()))


if __name__ == "__main__":
    main()
