#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import fatline_reboot as gate

OLD='11111111-1111-1111-1111-111111111111'
NEW='22222222-2222-2222-2222-222222222222'


class RebootContract(unittest.TestCase):
    def test_resume_never_sends_a_second_reboot_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source={'revision':'selected'}
            before={'boot':OLD,'containers':dict.fromkeys(gate.ROLES,'old')}
            after={'boot':NEW,'containers':dict.fromkeys(gate.ROLES,'new')}
            peer_before={'boot':'peer','containers':dict.fromkeys(gate.ROLES,'peer')}
            transaction={'id':'pending','phase':'requested','before':before,'peerBefore':peer_before,'adapterSource':source}
            (root/'reboot-transaction.json').write_text(json.dumps(transaction))
            (root/'recovery.json').write_text(json.dumps({'status':'installed','source':source,'boot':OLD}))
            link=SimpleNamespace(state={'boot':OLD},state_path=root/'state.json',root=root)
            peer=SimpleNamespace(state={'boot':'peer'})
            service=SimpleNamespace(root=root,link=link,state={'status':'active'},selection=lambda key:source,retain=lambda:None,execute=lambda action:None)
            peer_service=SimpleNamespace(state={'status':'active'},retain=lambda:None)
            with patch.object(gate,'Services',side_effect=[service,peer_service]), patch.object(gate,'wait_new_boot',return_value=NEW), patch.object(gate,'helper'), patch.object(gate,'observe',side_effect=[after,peer_before,after,after,peer_before]), patch.object(gate,'logmash_qualify'), patch.object(gate.subprocess,'run') as command:
                gate.run_gate(link,peer,resume=True)
                command.assert_not_called()
            self.assertEqual(json.loads((root/'reboot-qualification.json').read_text())['result'],'passed')

    def test_transition_rejects_same_boot_and_changed_peer(self):
        before={'boot':OLD,'containers':dict.fromkeys(gate.ROLES,'old')}
        after={'boot':NEW,'containers':dict.fromkeys(gate.ROLES,'new')}
        peer={'boot':'peer','containers':dict.fromkeys(gate.ROLES,'peer')}
        gate.validate_transition(before,after,peer,peer)
        with self.assertRaisesRegex(ValueError,'did not change'):
            gate.validate_transition(before,dict(after,boot=OLD),peer,peer)
        with self.assertRaisesRegex(ValueError,'VM2'):
            gate.validate_transition(before,after,peer,dict(peer,boot='changed'))
        after['containers']['logma']='old'
        with self.assertRaisesRegex(ValueError,'container did not change'):
            gate.validate_transition(before,after,peer,peer)

    def test_unavailable_authority_is_rejected_without_mutation(self):
        calls=[]
        def run(argv,env,capture,body,timeout):
            calls.append(body)
            return 'REBOOT_CAPABILITY=missing'
        with patch.object(gate,'run',side_effect=run):
            with self.assertRaisesRegex(ValueError,'noninteractive reboot authority'):
                gate.reboot_capability(SimpleNamespace(command=['ssh'],env={}))
        self.assertNotIn('systemctl reboot\n',calls[0])
        self.assertIn('CanReboot',calls[0])

    def test_reconciliation_resumes_after_first_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            record={'boot':OLD,'source':{'revision':'selected'}}
            (root/'recovery.json').write_text(json.dumps(record))
            link=SimpleNamespace(state={'boot':NEW},state_path=root/'state.json')
            transaction={'id':'transaction','before':{'boot':OLD},'after':{'boot':NEW},'adapterSource':record['source']}
            gate.reconcile(link,SimpleNamespace(root=root),transaction,root/'transaction.json')
            self.assertEqual(json.loads((root/'recovery.json').read_text())['boot'],NEW)
            self.assertEqual(transaction['phase'],'reconciled')
            record['boot']='foreign'
            (root/'recovery.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'binding changed'):
                gate.reconcile(link,SimpleNamespace(root=root),transaction,root/'transaction.json')

    def test_ssh_disconnect_is_not_boot_evidence(self):
        answers=[subprocess.CompletedProcess([],255,'','Connection closed'),
                 subprocess.CompletedProcess([],0,OLD+'\n',''),
                 subprocess.CompletedProcess([],0,NEW+'\n','')]
        with patch.object(gate.subprocess,'run',side_effect=answers),patch.object(gate.time,'sleep'):
            self.assertEqual(gate.wait_new_boot(SimpleNamespace(command=['ssh'],env={}),OLD),NEW)

    def test_changed_ssh_host_identity_is_never_accepted(self):
        result=subprocess.CompletedProcess([],255,'','Host key verification failed')
        with patch.object(gate.subprocess,'run',return_value=result):
            with self.assertRaisesRegex(ValueError,'SSH host identity changed'):
                gate.wait_new_boot(SimpleNamespace(command=['ssh'],env={}),OLD)


if __name__=='__main__': unittest.main()
