#!/usr/bin/env python3
"""Exercise domain boundaries and the sandbox composition sequencer."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from compositions import validate
from compose_runtime import Runtime


def plan():
    placements = {'host': {'kind': 'host', 'transport': 'bind'}}
    for i in (1, 2):
        placements['vm' + str(i)] = {'kind': 'coreos', 'transport': '9p',
            'container': 'coreos-vm' + str(i), 'sshPort': 2221 + i, 'reusePrimary': i == 1}
    return {'version': 1, 'name': 'shared-store-matrix', 'system': 'aarch64-linux',
        'placements': placements, 'domains': {
            'common': {'owner': {'placement': 'host', 'scopeStore': True},
                       'readers': list(placements), 'provisioning': 'existing-host-store'},
            'vm1-local': {'owner': {'placement': 'vm1', 'scopeStore': False},
                          'readers': ['vm1'], 'provisioning': 'deferred'},
            'guests-shared': {'owner': {'placement': 'host', 'scopeStore': False},
                             'readers': ['vm1', 'vm2'], 'provisioning': 'deferred'}},
        'workloads': {'shared-' + place + '-' + replica: {'placement': place, 'domain': 'common', 'access': 'read-only'}
                      for place in placements for replica in ('a', 'b')}}


class Contracts(unittest.TestCase):
    def test_valid_ownership_shapes(self):
        self.assertEqual(len(validate(plan())['workloads']), 6)

    def test_write_access_rejected(self):
        p = plan()
        p['workloads']['shared-vm1-a']['access'] = 'read-write'
        with self.assertRaisesRegex(ValueError, 'cannot write'):
            validate(p)

    def test_guest_only_domain_excludes_host_consumer(self):
        p = plan()
        p['workloads']['shared-host-a']['domain'] = 'guests-shared'
        with self.assertRaisesRegex(ValueError, 'cannot read'):
            validate(p)

    def test_vm_local_domain_excludes_other_vm(self):
        p = plan()
        p['workloads']['shared-vm2-a']['domain'] = 'vm1-local'
        with self.assertRaisesRegex(ValueError, 'cannot read'):
            validate(p)

    def test_vm_cannot_own_common_store(self):
        p = plan()
        p['domains']['common']['owner']['placement'] = 'vm1'
        with self.assertRaisesRegex(ValueError, 'host-owned'):
            validate(p)

    def test_distinct_ports_and_containers(self):
        for field in ('sshPort', 'container'):
            p = plan()
            p['placements']['vm2'][field] = p['placements']['vm1'][field]
            with self.assertRaises(ValueError):
                validate(p)

    def test_runtime_separates_vm_state_and_reuses_immutable_artifacts(self):
        runtime = Runtime.__new__(Runtime)
        runtime.plan = plan()
        runtime.scope = 'nix-xd-arm'
        runtime.env = {'COREOS_GUEST_PROBE_ROOTFS': '/stale', 'COREOS_ARTIFACT_STATE': '/stale'}
        runtime.primary = Path('/state/primary')
        runtime.root = Path('/state/matrix')
        host = runtime.environment('shared-host-a')
        first = runtime.environment('shared-vm1-a')
        second = runtime.environment('shared-vm2-a')
        self.assertEqual(host['NIX_XD_WORKLOAD_PLACEMENT'], 'host')
        self.assertNotIn('COREOS_GUEST_PROBE_ROOTFS', second)
        self.assertNotIn('COREOS_ARTIFACT_STATE', first)
        self.assertEqual(second['COREOS_ARTIFACT_STATE'], '/state/primary/starwisp')
        self.assertNotEqual(first['COREOS_STATE_ROOT'], second['COREOS_STATE_ROOT'])
        self.assertEqual(first['COREOS_NIX_STORE_VOLUME'], second['COREOS_NIX_STORE_VOLUME'])


if __name__ == '__main__':
    unittest.main()
