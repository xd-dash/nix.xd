#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
class BuilderStores(unittest.TestCase):
    def run_policy(self, peers='', volume='old-store', operation='builder_store_mounts'):
        env = dict(os.environ, NIX_XD_PEER_STORES=peers, NIX_XD_STORE_VOLUME=volume)
        return subprocess.run(['bash','-eu','-c','source lib/builder-stores.sh; builder_stores_init owner; '+operation],
                              cwd=ROOT, env=env, text=True, capture_output=True)
    def test_peer_aliases_and_legacy_volume_override(self):
        result = self.run_policy('agni=existing-agni grumble')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['Volume=old-store:/nix', 'Volume=existing-agni:/peer/agni:ro', 'Volume=nix-xd-grumble-store:/peer/grumble:ro'])
    def test_invalid_and_ambiguous_configuration_rejected(self):
        for peers in ('../bad','a=x a=y','a=old-store','a=x:rw','a=x\nb=y','a='):
            with self.subTest(peers=peers): self.assertNotEqual(self.run_policy(peers).returncode,0)
    def test_no_peers_does_not_add_mounts(self):
        self.assertEqual(self.run_policy().stdout, 'Volume=old-store:/nix\n')
    def test_missing_peer_fails_without_create(self):
        result=self.run_policy('grumble', operation='fake(){ [[ "$*" == "volume exists nix-xd-grumble-store" ]] && return 1; return 91; }; builder_stores_check fake')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Selected peer store is missing',result.stderr)
    def test_start_checks_peers_again(self):
        result=self.run_policy('a=x b=y', operation='builder_quadlet owner localhost/nix-xd:arm64 "Nix-Alpine ARM64 (owner)"')
        self.assertIn('ExecStartPre=/usr/bin/podman volume exists x\n',result.stdout)
        self.assertIn('ExecStartPre=/usr/bin/podman volume exists y\n',result.stdout)
        self.assertEqual(sum(line.startswith('Volume=') and not line.endswith(':ro') for line in result.stdout.splitlines()),1)
if __name__=='__main__': unittest.main()
