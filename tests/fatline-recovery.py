#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import fatline_recovery as gate
from fatline_services import Services


class RestartEvidence(unittest.TestCase):
    def test_declared_retry_retains_the_partially_installed_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = {'source':{'revision':'old'}, 'root':'old-root','bundle':'old-bundle','status':'installing'}
            (root / 'recovery.json').write_text(json.dumps(old))
            source = {'revision':'new','refreshFrom':['old'],'package':'coreos-services-vm1'}
            metadata = {'schema':1, 'logmaRev':'l', 'skymillRev':'s','ratelimiterRev':'r',
                'probe':'/nix/store/'+'b'*32+'-probe/bin/fatline-services-probe'}
            def owner(*args):
                if args[0] == 'nix': return '/nix/store/'+'a'*32+'-bundle'
                return json.dumps(metadata) if args[-1].endswith('metadata.json') else '#!/bin/bash'
            services = SimpleNamespace(root=root, state={'status':'active','metadata':metadata},
                selection=lambda key:source, retain=lambda:None,
                link=SimpleNamespace(scope='scope',state={'boot':'same'},runtime=SimpleNamespace(owner=owner)))
            with patch.object(gate, 'invoke'):
                gate.prepare(services)
            record = json.loads((root / 'recovery.json').read_text())
            self.assertEqual(record['status'], 'installed')
            self.assertEqual(record['retiredRoots'], [{'root':'old-root','bundle':'old-bundle'}])
            old['status'] = 'installed'
            (root / 'recovery.json').write_text(json.dumps(old))
            with self.assertRaisesRegex(ValueError, 'migrate explicitly'): gate.prepare(services)

    def test_lost_acknowledgement_marks_failed_and_retains_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {'source':{'revision':'pinned'}, 'status':'installed', 'boot':'same-boot', 'root':'protected'}
            (root / 'recovery.json').write_text(json.dumps(record))
            calls = []
            services = SimpleNamespace(root=root, link=SimpleNamespace(state={'boot':'same-boot'}),
                selection=lambda key:record['source'], retain=lambda:calls.append('retain'))
            with patch.object(gate, 'invoke', side_effect=ValueError('lost acknowledgement')):
                with self.assertRaisesRegex(ValueError, 'lost acknowledgement'): gate.qualify(services)
            self.assertEqual(calls, ['retain'])
            self.assertEqual(json.loads((root / 'recovery.json').read_text()), record)
            evidence = json.loads((root / 'restart-qualification.json').read_text())
            self.assertEqual(evidence['result'], 'failed')
            self.assertFalse(evidence['rebootQualified'])

    def test_changed_boot_cannot_reuse_restart_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = {'revision':'pinned'}
            (root / 'recovery.json').write_text(json.dumps({'source':source,'status':'installed','boot':'old'}))
            services = SimpleNamespace(root=root, link=SimpleNamespace(state={'boot':'new'}), selection=lambda key:source)
            with self.assertRaisesRegex(ValueError, 'Boot changed'): gate.qualify(services)

    def test_installed_startup_helper_is_retained_with_services(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            (root / 'recovery.json').write_text(json.dumps({'root':'recovery-root','bundle':'recovery-bundle'}))
            services = Services.__new__(Services)
            services.root = root
            services.state = {'root':'application-root','bundle':'application-bundle'}
            services.link = SimpleNamespace(retain=lambda:None, runtime=SimpleNamespace(owner=lambda *args:calls.append(args)))
            services.retain()
            self.assertEqual(calls[-1][-2:], ('recovery-root','recovery-bundle'))


if __name__ == '__main__': unittest.main()
