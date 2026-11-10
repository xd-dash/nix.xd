#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import fatline_rebootstrap as gate
import compose_runtime


class ReplacementContract(unittest.TestCase):
    def test_empty_exported_public_key_uses_the_private_key_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            private=Path(directory)/'identity'
            public=Path(str(private)+'.pub')
            public.write_text('ssh-ed25519 AAAA fixture-comment\n')
            with patch.dict(os.environ,{'COREOS_SSH_KEY':str(private),'COREOS_SSH_PUBLIC_KEY':''}):
                self.assertEqual(gate.public_key(),'ssh-ed25519 AAAA')

    def test_physical_vm1_binding_preserves_vm2_artifacts(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(compose_runtime,'REPO',Path(directory)):
            runtime=compose_runtime.Runtime({'NIX_XD_PROVIDER':'podman','NIX_XD_SCOPE':'owner','COREOS_STATE_ROOT':directory+'/original'})
            runtime.plan={'placements':{
                'vm1':{'kind':'coreos','container':'coreos-starwisp','sshPort':2222,'reusePrimary':True},
                'vm2':{'kind':'coreos','container':'coreos-store-matrix-vm2','sshPort':2223,'reusePrimary':False}},
                'workloads':{'one':{'placement':'vm1'},'two':{'placement':'vm2'}}}
            runtime.binding_overrides['vm1']={'schema':1,'logical':'vm1','baseContainer':'coreos-starwisp','container':'replacement','sshPort':2224,'stateRoot':directory+'/replacement'}
            self.assertEqual(runtime.environment('one')['COREOS_STATE_ROOT'],directory+'/replacement')
            self.assertEqual(runtime.environment('two')['COREOS_ARTIFACT_STATE'],directory+'/original/starwisp')
            runtime.binding_overrides['vm1']['baseContainer']='different'
            with self.assertRaisesRegex(ValueError,'differs from declared'):runtime.environment('one')

    def test_bootstrap_requires_wisp_policy_and_rejects_root_login(self):
        key='ssh-ed25519 AAAA'
        policy='subject.user == "wisp" && action.id == "org.freedesktop.login1.reboot"'
        value={'passwd':{'users':[{'name':'wisp','sshAuthorizedKeys':[key]}]},
            'storage':{'files':[{'path':'/etc/polkit-1/rules.d/60-wisp-reboot.rules','contents':{'source':'data:;base64,'+base64.b64encode(policy.encode()).decode()}}]},
            'systemd':{'units':[{'name':'var-mnt-nixstore.mount','enabled':True,'contents':'Options=ro,nodev'}]}}
        gate.ignition_contract(json.dumps(value),key)
        value['passwd']['users'].append({'name':'root','sshAuthorizedKeys':[key]})
        with self.assertRaisesRegex(ValueError,'Root SSH'):gate.ignition_contract(json.dumps(value),key)

    def test_credential_evidence_detects_secret_changes_but_allows_path_rebinding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'credentials').mkdir();(root/'services/credentials/logma').mkdir(parents=True)
            (root/'credentials/subscriber').write_text('private fixture')
            (root/'credentials/subscriber.json').write_text('old path')
            (root/'services/credentials/logma/api-key').write_text('private API fixture')
            before=gate.credentials(root)
            (root/'credentials/subscriber.json').write_text('new path')
            self.assertEqual(gate.credentials(root),before)
            (root/'services/credentials/logma/api-key').write_text('changed')
            self.assertNotEqual(gate.credentials(root),before)

    def test_retirement_can_resume_after_runner_already_stopped(self):
        original=SimpleNamespace(runtime=SimpleNamespace(podman=['podman']),env={},command=['ssh'],scope='scope')
        tx={'before':{'boot':'old'},'oldBinding':{'container':'old-runner'},'oldRunnerId':'expected'}
        with patch.object(gate,'run',return_value=json.dumps([{'Id':'expected','State':{'Running':False}}])) as run:
            gate.retire_original(original,tx)
            self.assertEqual(run.call_count,1)
        with patch.object(gate,'run',return_value=json.dumps([{'Id':'another','State':{'Running':True}}])) as run:
            with self.assertRaisesRegex(ValueError,'identity changed'):gate.retire_original(original,tx)
            self.assertEqual(run.call_count,1)

    def test_failed_candidate_qualification_never_stops_original_or_writes_binding(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'NIX_XD_SYSTEM':'aarch64-linux'}):
            root=Path(directory)
            tx={'id':'candidate','phase':'restored','oldBinding':{},'newBinding':{},'peerBefore':{},
                'bootstrap':'bootstrap','recoverySelection':'recovery','probeSelection':'probe'}
            (root/'transaction.json').write_text(json.dumps(tx))
            (root/'rebootstrap.json').write_text(json.dumps({'transaction':str(root/'transaction.json')}))
            runtime=SimpleNamespace(binding_overrides={},transport_command=lambda *args:(['ssh'],{}),environment=lambda name:{})
            original=SimpleNamespace(root=root,profile='vm1',runtime=runtime)
            peer=SimpleNamespace()
            services=SimpleNamespace(state={'status':'active'},retain=lambda:None,
                selection=lambda key:{'servicesRecovery':'recovery','servicesProbe':'probe'}[key])
            candidate=SimpleNamespace(root=root/'candidate');(candidate.root/'services').mkdir(parents=True)
            with patch.object(gate,'Services',return_value=services),patch.object(gate,'source_selection',return_value='bootstrap'),patch.object(gate,'observe',return_value={}),patch.object(gate,'candidate_link',return_value=candidate),patch.object(gate,'run_gate',side_effect=ValueError('candidate failed')),patch.object(gate,'run') as command,patch.object(gate,'retire_original') as retire:
                with self.assertRaisesRegex(ValueError,'candidate failed'):gate.run_rebootstrap(original,peer)
                command.assert_not_called();retire.assert_not_called()
            self.assertEqual(json.loads((root/'transaction.json').read_text())['phase'],'restored')


if __name__=='__main__':unittest.main()
