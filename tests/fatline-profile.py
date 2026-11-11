#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import fatline_profile as profile


class SimpleApply(unittest.TestCase):
    def test_failed_apply_is_retryable_and_never_selects_a_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'generation.json').write_text('{}')
            candidate=root/'candidate';(candidate/'services').mkdir(parents=True)
            source={'revision':'selected'}
            operation={'id':'generation','source':source,'root':str(candidate),'phase':'applying','peerBefore':{}}
            (root/'profile-operation.json').write_text(json.dumps(operation))
            (candidate/'state.json').write_text(json.dumps({'boot':'boot'}))
            (candidate/'services/startup-profile.json').write_text(json.dumps({'source':source}))
            original=SimpleNamespace(root=root,control_root=root,scope='scope')
            services=SimpleNamespace(root=root,state={'status':'active'},retain=lambda:None)
            with patch.object(profile,'selected',return_value=source),patch.object(profile,'Services',return_value=services),patch.object(profile,'observe',return_value={}),patch.object(profile,'apply_profile',side_effect=ValueError('startup failed')),patch.object(profile,'activate') as activate:
                with self.assertRaisesRegex(ValueError,'startup failed'):profile.run_profile(original,SimpleNamespace())
                activate.assert_not_called()
            self.assertEqual(json.loads((root/'profile-operation.json').read_text())['phase'],'applying')

    def test_failed_reliability_gate_records_failure_without_selecting_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source={'revision':'selected'}
            (root/'startup-profile.json').write_text(json.dumps({'status':'installed','source':source,'boot':'boot'}))
            link=SimpleNamespace(root=root,state={'boot':'boot'},command=['ssh'],env={})
            services=SimpleNamespace(root=root,retain=lambda:None)
            with patch.object(profile,'Services',return_value=services),patch.object(profile,'selected',return_value=source),patch.object(profile,'observe',return_value={'boot':'peer'}),patch.object(profile,'run',return_value='boot'),patch.object(profile,'credentials',return_value={}),patch.object(profile,'invoke',side_effect=ValueError('recovery failed')),patch('fatline_recovery.diagnose'),patch.object(profile,'activate') as activate:
                with self.assertRaisesRegex(ValueError,'recovery failed'):profile.run_reliability(link,SimpleNamespace(),'qualify-reliability')
                activate.assert_not_called()
            receipt=json.loads((root/'reliability-qualification.json').read_text())
            self.assertEqual(receipt['result'],'failed')
            self.assertFalse(receipt['rebootQualified'])
            self.assertFalse(receipt['parentVmReplacementQualified'])

    def test_zero_exit_without_profile_ack_is_not_success(self):
        link=SimpleNamespace(scope='scope',state={'boot':'boot'},command=['ssh'],env={})
        record={'bundle':'/nix/store/'+'a'*32+'-profile','probe':'/nix/store/probe','sha256':'digest'}
        with patch.object(profile,'run',return_value=''):
            with self.assertRaisesRegex(ValueError,'acknowledgement missing'):profile.invoke(link,record,'status')


if __name__=='__main__':unittest.main()
