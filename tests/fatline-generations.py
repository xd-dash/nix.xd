#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
import fatline_generations as generations


class AtomicGeneration(unittest.TestCase):
    def fixture(self,root):
        candidate=root/'candidate';(candidate/'services').mkdir(parents=True)
        (candidate/'state.json').write_text('{}')
        (candidate/'services/state.json').write_text(json.dumps({'source':{'revision':'application'},'bundle':'/nix/store/services'}))
        (candidate/'services/recovery.json').write_text(json.dumps({'source':{'revision':'startup'},'bundle':'/nix/store/startup'}))
        link=SimpleNamespace(root=candidate,runtime=SimpleNamespace(scope='owner'),profile='vm1',scope='fatline-arm-vm1',
            state={'boot':'new','plan':{'system':'aarch64-linux'},'archive':'/nix/store/rootfs','agniRev':'transport','bundle':'/nix/store/transport'})
        binding={'schema':1,'logical':'vm1','baseContainer':'original','container':'replacement','sshPort':2224,'stateRoot':str(root/'guest')}
        tx={'id':'generation','newBinding':binding,'storeVolume':'owner-store','bootstrap':{'revision':'bootstrap'},'credentials':{'subscriber':'hash'}}
        receipt={'result':'passed','transaction':{'after':{'boot':'new'}}}
        return link,tx,receipt

    def test_activation_selects_generation_without_overwriting_old_state(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(generations,'REPO',Path(directory)):
            root=Path(directory);link,tx,receipt=self.fixture(root)
            old=root/'old';old.mkdir();(old/'state.json').write_text('original state')
            generations.activate(link,tx,receipt)
            self.assertEqual((old/'state.json').read_text(),'original state')
            self.assertEqual(generations.active_root('owner','vm1',old),link.root)
            descriptor=json.loads((root/'.state/vm-bindings/owner/vm1.json').read_text())
            self.assertEqual(descriptor['generation'],'generation')
            self.assertEqual(descriptor['fatlineRoot'],str(link.root))
            generations.activate(link,tx,receipt)

    def test_unqualified_generation_cannot_replace_active_record(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(generations,'REPO',Path(directory)):
            root=Path(directory);link,tx,receipt=self.fixture(root)
            receipt['result']='failed'
            with self.assertRaisesRegex(ValueError,'qualification failed'):generations.activate(link,tx,receipt)
            self.assertFalse((root/'.state/vm-bindings/owner/vm1.json').exists())

    def test_services_only_qualification_does_not_claim_reboot(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(generations,'REPO',Path(directory)):
            root=Path(directory);link,tx,receipt=self.fixture(root)
            receipt={'result':'passed','observation':{'boot':'new'},'gates':{'services':True,'hostSubscriber':True,'reboot':False}}
            generations.activate(link,tx,receipt)
            manifest=json.loads((link.root/'generation.json').read_text())
            self.assertFalse(manifest['qualification']['gates']['reboot'])
            receipt['gates']['hostSubscriber']=False
            with self.assertRaisesRegex(ValueError,'lacks service or host subscriber'):generations.activate(link,tx,receipt)

    def test_changed_manifest_cannot_be_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(generations,'REPO',Path(directory)):
            root=Path(directory);link,tx,receipt=self.fixture(root)
            generations.activate(link,tx,receipt)
            manifest=json.loads((link.root/'generation.json').read_text());manifest['guest']['sshPort']=9999
            (link.root/'generation.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'manifest and activation record differ'):
                generations.active_root('owner','vm1',root/'old')
            with self.assertRaisesRegex(ValueError,'manifest changed'):
                generations.activate(link,tx,receipt)


if __name__=='__main__':unittest.main()
