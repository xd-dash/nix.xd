#!/usr/bin/env python3
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import fatline_logmash as gate


class ApplicationGate(unittest.TestCase):
    def exercise(self, deny='expected', deliver=True, resource=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / '.state/wisp-go/smoke'
            binary.parent.mkdir(parents=True)
            binary.write_text('binary')
            (binary.parent / 'revision').write_text('a' * 40)
            credentials = root / 'credentials'
            credentials.mkdir()
            secret = 'private-test-credential-' * 3
            (credentials / 'subscriber').write_text(secret)
            (credentials / 'subscriber.json').write_text(json.dumps({
                'username':'subscriber', 'passwordFile':str(credentials / 'subscriber'),
                'channel':'tenant:qualification', 'payload':'unique-message'}))
            calls = []
            processes = []
            link = SimpleNamespace(root=root, env={}, scope='tenant',
                runtime=SimpleNamespace(primary=root), config={'placement':{'sshPort':2222}},
                state={'agniRev':'agni', 'boot':'boot', 'aclDigest':'digest'},
                retain=lambda: calls.append('retain'), guest=lambda action: calls.append(action))

            class Process:
                def __init__(self, command, **options):
                    self.command = command
                    self.returncode = None
                    self.socket = root / 'logmash.sock'
                    self.tunnel = command[1] == 'wisp'
                    self.env = options['env']
                    if self.tunnel:
                        self.socket.touch()
                        options['stdout'].write('WISP_FORWARD_READY=true\n')
                    else:
                        options['stdout'].write('logmash: ready source=us:vm1\n')
                        if deliver:
                            options['stdout'].write('us:vm1:tenant:qualification\t' + ('d'*48 if resource else 'unique-message') + '\n')
                    options['stdout'].flush()
                    processes.append(self)
                def poll(self): return self.returncode
                def send_signal(self, value):
                    self.returncode = 0
                    if self.tunnel: self.socket.unlink()
                def wait(self, timeout): return self.returncode
                def terminate(self): self.send_signal(15)
                def kill(self): self.send_signal(9)

            def negative(command, **options):
                marker = 'NOPERM' if command[-1].endswith('foreign:qualification') else 'WRONGPASS'
                return subprocess.CompletedProcess(command, 1 if deny == 'expected' else 0,
                                                   stdout=marker if deny == 'expected' else '')

            class ResourceServices:
                def __init__(self, link): self.state = {'source':{'revision':'fixture'}}
                def dispatch(self, path):
                    body = json.loads(path.read_text())
                    if body['Channel'] != 'tenant:qualification' or body['Payload'] != 'd'*48:
                        raise ValueError('incorrect resource binding')
                    calls.append('resource-dispatch')

            original_wait = gate.wait_log
            def wait(process, path, expected, timeout):
                if not deliver and '\t' in expected:
                    raise ValueError('missing delivery')
                return original_wait(process, path, expected, timeout)

            with patch.object(gate, 'REPO', root), patch.dict(os.environ, {'WISP_SMOKE_REV':'a' * 40,
                    'COREOS_SSH_KEY':'/host/key'}), patch.object(gate.subprocess, 'Popen', Process), \
                    patch.object(gate.subprocess, 'run', negative), patch.object(gate, 'wait_log', wait), patch('fatline_services.Services', ResourceServices), patch.object(gate.secrets,'token_hex',return_value='d'*48), \
                    contextlib.redirect_stdout(io.StringIO()):
                if deny != 'expected' or not deliver:
                    with self.assertRaises(ValueError): gate.qualify(link, resource=resource)
                else:
                    gate.qualify(link, resource=resource)
            result = json.loads((root / ('resource-logmash-qualification.json' if resource else 'logmash-qualification.json')).read_text())
            self.assertEqual(result['result'], 'passed' if deny == 'expected' and deliver else 'failed')
            self.assertFalse((root / 'logmash.sock').exists())
            self.assertTrue(all(process.poll() == 0 for process in processes))
            self.assertNotIn('stop', calls)
            if resource: self.assertIn('resource-dispatch', calls)
            for process in processes:
                self.assertNotIn(secret, ' '.join(process.command))
                if process.tunnel:
                    self.assertNotIn('LOGMASH_REDIS_US_VM1_PASSWORD', process.env)

    def test_delivery_cancellation_and_cleanup(self): self.exercise()
    def test_resource_mode_uses_resource_producer(self): self.exercise(resource=True)
    def test_unexpected_auth_success_fails_gate_and_cleans_tunnel(self): self.exercise(deny='accepted')
    def test_missing_delivery_fails_gate_and_cleans_both_processes(self): self.exercise(deliver=False)


if __name__ == '__main__':
    unittest.main()
