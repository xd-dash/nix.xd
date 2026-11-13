#!/usr/bin/env python3
"""Static contract regression; runtime internet and 9P gates remain separate."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from shoal_contract import check, ALL_WORLDS, ROLES


def fixture(worlds):
    guests = ["farcaster", *ALL_WORLDS[:worlds]]
    placements = {"host": {"kind": "host", "transport": "bind"}}
    domains = {"common": {"owner": {"placement": "host", "scopeStore": True},
                          "readers": ["host", *guests], "provisioning": "existing-host-store"}}
    workloads = {
        "host-a": {"placement": "host", "domain": "common", "access": "read-only"},
        "host-b": {"placement": "host", "domain": "common", "access": "read-only"},
    }
    for n, guest in enumerate(guests):
        placements[guest] = {"kind": "coreos", "transport": "9p",
                             "container": "coreos-shoal-" + guest, "sshPort": 2322 + n}
        domains[guest + "-local"] = {
            "owner": {"placement": guest, "scopeStore": False}, "readers": [guest],
            "provisioning": "deferred",
        }
        for suffix in ("-a", "-b"):
            workloads[guest + suffix] = {"placement": guest, "domain": "common", "access": "read-only"}
    return {
        "version": 1, "name": "shoal", "system": "aarch64-linux",
        "placements": placements, "domains": domains, "workloads": workloads,
        "topology": {
            "name": "shoal", "region": "regional", "addressFamilies": ["ipv4", "ipv6"],
            "farcaster": "farcaster", "members": ["farcaster", *ALL_WORLDS],
            "active": guests, "maxWorlds": 7,
            "egress": {"gateway": "farcaster", "proxy": "squid", "protocol": "http-connect",
                       "directWorldEgress": "deny", "qualified": False},
            "service": {"owner": "agni", "farcasterRoles": list(ROLES), "client": "logmash"},
            "storage": {"owner": "host", "common": "read-only-9p",
                        "guestContainers": "read-only-bind-from-9p",
                        "guestLocal": "guest-owned", "crossVmWritableStore": False},
        },
    }


class ShoalContractTests(unittest.TestCase):
    def test_bounded_topology_scales_without_changing_storage_contract(self):
        for worlds, members in ((0, 1), (1, 2), (7, 8)):
            with self.subTest(worlds=worlds):
                result = check(fixture(worlds), worlds)
                self.assertEqual(result["members"], members)
                self.assertEqual(result["internet"], "unqualified")

    def test_world_cannot_write_common_store(self):
        plan = fixture(1)
        plan["workloads"]["world1-a"]["access"] = "read-write"
        with self.assertRaises(ValueError):
            check(plan, 1)

    def test_world_local_store_not_exported_to_other_vm(self):
        plan = fixture(1)
        plan["domains"]["farcaster-local"]["readers"].append("world1")
        with self.assertRaisesRegex(ValueError, "guest-scoped"):
            check(plan, 1)

    def test_no_direct_internet_claim_without_packet_qualification(self):
        for key, value in (("directWorldEgress", "allow"), ("qualified", True)):
            plan = fixture(1)
            plan["topology"]["egress"][key] = value
            with self.assertRaisesRegex(ValueError, "unqualified"):
                check(plan, 1)

    def test_dual_stack_required(self):
        plan = fixture(1)
        plan["topology"]["addressFamilies"] = ["ipv4"]
        with self.assertRaisesRegex(ValueError, "address families"):
            check(plan, 1)

    def test_shoal_has_exactly_eight_logical_members(self):
        plan = fixture(7)
        plan["topology"]["members"].pop()
        with self.assertRaisesRegex(ValueError, "seven Worlds"):
            check(plan, 7)


if __name__ == "__main__":
    unittest.main()
