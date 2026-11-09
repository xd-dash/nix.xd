#!/usr/bin/env python3
"""Exercise domain boundaries and the sandbox composition sequencer."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from compositions import validate
from compose_runtime import Runtime, write_json


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


class Sequencer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Runtime.__new__(Runtime)
        self.runtime.plan = plan()
        self.runtime.plan['sourceRevision'] = 'a' * 40
        self.runtime.root = Path(self.temp.name)
        self.runtime.env = {'NIX_XD_SYSTEM': 'aarch64-linux'}
        self.calls = []
        self.snapshots = {}
        for index, (name, binding) in enumerate(self.runtime.plan['workloads'].items()):
            self.snapshots[name] = {'ISOLATION_CONTAINER_ID': 'container-' + name,
                'ISOLATION_BOOT_ID': 'boot-' + binding['placement'],
                'ISOLATION_ROOT_FINGERPRINT': 'roots-' + name,
                'ISOLATION_PID_NAMESPACE': 'pid-' + str(index),
                'ISOLATION_NIX_PATH': '/nix/store/nix/bin/nix',
                'ISOLATION_HELLO_PATH': '/nix/store/hello'}
        self.runtime.probe = self.probe
        self.runtime.roots = lambda name: self.snapshots[name]['ISOLATION_ROOT_FINGERPRINT']
        self.runtime.workload = self.workload
        self.runtime.control = lambda *args: json.dumps({'active': None, 'rootsRetained': False})

    def probe(self, names, token, write=False):
        return {name: dict(self.snapshots[name]) for name in names}

    def workload(self, name, action, **extra):
        self.calls.append((name, action, extra))
        if action == 'recreate' and not extra:
            self.snapshots[name]['ISOLATION_CONTAINER_ID'] += '-replacement'

    def test_recreation_visits_all_placements_and_leaves_final_evidence(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.runtime.qualify()
        pauses = [(name, extra) for name, action, extra in self.calls if extra]
        self.assertEqual({self.runtime.plan['workloads'][name]['placement'] for name, _ in pauses},
                         {'host', 'vm1', 'vm2'})
        self.assertEqual(len(pauses), 3)
        evidence = json.loads((self.runtime.root / 'qualification.json').read_text())
        self.assertEqual(evidence['result'], 'passed')
        self.assertEqual(len(evidence['readers']), 6)

    def test_peer_replacement_during_victim_stop_fails_gate(self):
        original = self.workload
        def disrupt(name, action, **extra):
            original(name, action, **extra)
            if extra:
                peer = next(n for n in self.snapshots if n != name)
                self.snapshots[peer]['ISOLATION_CONTAINER_ID'] = 'unexpected-replacement'
        self.runtime.workload = disrupt
        with self.assertRaisesRegex(ValueError, 'Peer identity'):
            self.runtime.qualify()
        self.assertFalse((self.runtime.root / 'qualification.json').exists())

    def test_shared_boot_identity_fails_before_recreation(self):
        for snapshot in self.snapshots.values():
            snapshot['ISOLATION_BOOT_ID'] = 'same-boot'
        with self.assertRaisesRegex(ValueError, 'independently booted'):
            self.runtime.qualify()
        self.assertFalse(self.calls)

    def test_failed_recheck_cannot_leave_stale_pass(self):
        write_json(self.runtime.root / 'qualification.json', {'result': 'passed'})
        self.runtime.resolve = lambda fresh=False: self.runtime.plan
        self.runtime.verify_bindings = lambda: None
        self.runtime.qualify = lambda: (_ for _ in ()).throw(ValueError('runtime unavailable'))
        with self.assertRaisesRegex(ValueError, 'runtime unavailable'):
            self.runtime.execute('qualify')
        evidence = json.loads((self.runtime.root / 'qualification.json').read_text())
        self.assertEqual(evidence['result'], 'unqualified')

    def test_binding_rejects_workload_from_different_revision(self):
        name = next(iter(self.runtime.plan['workloads']))
        state = {'active': None, 'prepared': 'generation', 'generations': {'generation': {
            'manifest': {'source': {'revision': 'b' * 40}, 'system': 'aarch64-linux',
                         'declaration': {'placement': 'host', 'storeDomain': 'common',
                                         'qualification': {'mode': 'running'}}}}}}
        self.runtime.control = lambda *args: json.dumps(state)
        with self.assertRaisesRegex(ValueError, 'source or architecture'):
            self.runtime.verify_bindings()


if __name__ == '__main__':
    unittest.main()
