#!/usr/bin/env python3
"""Exercise domain boundaries and the sandbox composition sequencer."""
import contextlib
import fcntl
import signal
import subprocess
import io
import json
import os
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

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
        self.runtime.resolve = lambda fresh=False, stopping=False: self.runtime.plan
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
        self.runtime.batch = lambda requests: {r['name']: state for r in requests}
        with self.assertRaisesRegex(ValueError, 'source or architecture'):
            self.runtime.verify_bindings()


class BatchedProbes(unittest.TestCase):
    def test_one_connection_per_placement_and_roots_rechecked(self):
        runtime = Runtime.__new__(Runtime)
        runtime.plan = plan()
        batches, groups = [], []
        def batch(requests):
            batches.append(requests)
            return {r['name']: {'generation': 'generation', 'fingerprint': 'roots', 'script': ''} for r in requests}
        runtime.batch = batch
        def placement(place, names, bundle):
            groups.append((place, names))
            return {name: {'ISOLATION_ROOT_FINGERPRINT': 'roots', 'ISOLATION_CONTAINER_ID': name,
                            'ISOLATION_BOOT_ID': place} for name in names}, 0
        runtime.placement_probe = placement
        names = list(runtime.plan['workloads'])
        with contextlib.redirect_stdout(io.StringIO()):
            results = runtime.probe(names, 'f' * 32, write=True)
        self.assertEqual(set(results), set(names))
        self.assertEqual(len(groups), 3)
        self.assertTrue(all(len(readers) == 2 for _, readers in groups))
        self.assertEqual(len(batches), 2)
        self.assertEqual({r['action'] for r in batches[0]}, {'isolation'})
        self.assertEqual({r['action'] for r in batches[1]}, {'roots'})

    def test_stop_can_use_old_staged_revision_after_host_update(self):
        runtime = Runtime.__new__(Runtime)
        runtime.flake = '/workspaces/nix.xd'
        runtime.env = {'NIX_XD_SYSTEM': 'aarch64-linux', 'NIX_XD_WORKLOAD_REV': 'b' * 40}
        runtime.owner = lambda *args: 'a' * 40
        pinned = []
        runtime.pin_controller = pinned.append
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            old = plan()
            old['sourceRevision'] = 'a' * 40
            write_json(runtime.root / 'plan.json', old)
            self.assertEqual(runtime.resolve(stopping=True)['sourceRevision'], 'a' * 40)
            self.assertEqual(pinned, ['a' * 40])
            with self.assertRaisesRegex(ValueError, 'Stage the selected'):
                runtime.resolve()

    def test_both_readers_execute_on_one_connection_with_separate_shell_scopes(self):
        runtime = Runtime.__new__(Runtime)
        runtime.plan = plan()
        runtime.environment = lambda name: dict(os.environ)
        names = ['shared-host-a', 'shared-host-b']
        bundle = {}
        for name in names:
            script = "set -eu\n"
            for key, value in {'WORKLOAD_ISOLATION_OK': 'generation', 'ISOLATION_CONTAINER_ID': name,
                'ISOLATION_BOOT_ID': 'host-boot', 'ISOLATION_PID_NAMESPACE': name,
                'ISOLATION_NIX_PATH': '/nix/store/nix', 'ISOLATION_HELLO_PATH': '/nix/store/hello',
                'ISOLATION_STATE': 'private', 'ISOLATION_STORE': 'read-only'}.items():
                script += "printf '%s\\n' '" + key + '=' + value + "'\n"
            bundle[name] = {'script': script, 'generation': 'generation', 'fingerprint': 'roots'}
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            with patch('compose_runtime.platform.system', return_value='Linux'):
                results, elapsed = runtime.placement_probe('host', names, bundle)
            self.assertEqual(set(results), set(names))
            self.assertNotEqual(results[names[0]]['ISOLATION_CONTAINER_ID'], results[names[1]]['ISOLATION_CONTAINER_ID'])

    def test_placement_rejects_missing_reader_acknowledgement(self):
        runtime = Runtime.__new__(Runtime)
        runtime.plan = plan()
        runtime.environment = lambda name: {}
        with tempfile.TemporaryDirectory() as directory:
            runtime.root = Path(directory)
            output = 'COMPOSITION_READER_BEGIN=shared-host-a\nCOMPOSITION_READER_END=shared-host-a\n'
            with patch('compose_runtime.platform.system', return_value='Linux'), \
                 patch('compose_runtime.run', return_value=output):
                with self.assertRaisesRegex(ValueError, 'acknowledgement missing'):
                    runtime.placement_probe('host', ['shared-host-a'],
                        {'shared-host-a': {'script': ':', 'generation': 'generation', 'fingerprint': 'roots'}})


class Cancellation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Runtime.__new__(Runtime)
        self.runtime.root = Path(self.temporary.name)

    def test_idle_cancel_does_not_signal_anything(self):
        with patch('compose_runtime.os.kill') as kill, contextlib.redirect_stdout(io.StringIO()):
            self.runtime.cancel()
        kill.assert_not_called()

    def test_cancel_only_signals_verified_controller_and_descendants(self):
        listing = subprocess.CompletedProcess([], 0, stdout='234567\n234599\n')
        tables = ['234567 1 python3 lib/compose_runtime.py qualify\n234568 234567 ssh guest bash -se\n234599 1 unrelated-program\n',
                  '234567 1\n234568 234567\n234569 234568\n234599 1\n']
        with patch('compose_runtime.fcntl.flock', side_effect=[BlockingIOError(), None]), \
             patch('compose_runtime.shutil.which', return_value='/usr/sbin/lsof'), \
             patch('compose_runtime.subprocess.run', return_value=listing), \
             patch('compose_runtime.subprocess.check_output', side_effect=tables), \
             patch('compose_runtime.os.kill') as kill, contextlib.redirect_stdout(io.StringIO()):
            self.runtime.cancel()
        self.assertEqual(kill.call_args_list[0].args, (234567, signal.SIGSTOP))
        signalled = [call.args for call in kill.call_args_list]
        self.assertIn((234568, signal.SIGTERM), signalled)
        self.assertIn((234569, signal.SIGTERM), signalled)
        self.assertIn((234567, signal.SIGTERM), signalled)
        self.assertEqual(signalled[-1], (234567, signal.SIGCONT))
        self.assertNotIn(234599, [pid for pid, _ in signalled])

    def test_unknown_lock_holder_is_not_signalled(self):
        listing = subprocess.CompletedProcess([], 0, stdout='234599\n')
        with patch('compose_runtime.fcntl.flock', side_effect=BlockingIOError()), \
             patch('compose_runtime.shutil.which', return_value='/usr/sbin/lsof'), \
             patch('compose_runtime.subprocess.run', return_value=listing), \
             patch('compose_runtime.subprocess.check_output', return_value='234599 1 unrelated-program\n'), \
             patch('compose_runtime.os.kill') as kill:
            with self.assertRaisesRegex(ValueError, 'no processes signalled'):
                self.runtime.cancel()
        kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
