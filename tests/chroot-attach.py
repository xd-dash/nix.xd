import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class Attach(unittest.TestCase):
    def fixture(self,home,conflict=False):
        tools=home/'bin';tools.mkdir()
        unit=home/'.config/containers/systemd/fixture.container';unit.parent.mkdir(parents=True)
        unit.write_text('[Container]\nContainerName=fixture\nVolume=authoritative:/nix\n')
        (home/'state').write_text(json.dumps({'attached':False,'conflict':conflict,'restarts':0,'profile':False}))
        mock=tools/'podman';mock.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['HOME'])/'state';state=json.loads(p.read_text());a=sys.argv[1:]
if a[0]=='info':print('true')
elif a[:2]==['ps','-aq']:print('owner')
elif a[0]=='inspect':
 f=a[-1]
 if 'Privileged' in f:print('false')
 elif 'MaskedPaths' in f:
  if not state['profile']:print('/proc/kcore\\n/proc/sys')
 elif 'State.Running' in f:print('true')
 elif '.Image' in f:print('sha256:fixture')
 elif '.Name'==f.strip('{}'):print('fixture')
 elif '.RW' in f:
  if state['attached']:print('isolated /stores/grumble true')
 else:
  print('authoritative|/nix')
  if state['conflict']:print('other|/stores/grumble')
  elif state['attached']:print('isolated|/stores/grumble')
elif a[0]=='volume':sys.exit(0)
elif a[0]=='exec':
 if a[-1]=='/proc/self/mountinfo' and not state['profile']:print('/proc/sys')
elif a[0]=='run':pass
else:raise SystemExit('Unexpected '+repr(a))
''');mock.chmod(0o755)
        mock=tools/'systemctl';mock.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['HOME'])/'state';s=json.loads(p.read_text())
if 'show' in sys.argv:print('loaded')
if 'restart' in sys.argv:
 s.update(attached=True,restarts=s['restarts']+1,profile=(Path(os.environ['HOME'])/'.config/containers/systemd/fixture.container.d/30-nix-chroot-profile.conf').exists());p.write_text(json.dumps(s))
''');mock.chmod(0o755)
        return dict(os.environ,HOME=str(home),PATH=str(tools)+':'+os.environ['PATH']),unit

    def test_adds_only_dropin_and_second_apply_reuses_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,unit=self.fixture(home);original=unit.read_bytes()
            for _ in range(2):subprocess.run(['bash',str(ROOT/'runtime/chroot-attach.sh'),'fixture','grumble','isolated'],env=env,check=True,capture_output=True)
            self.assertEqual(unit.read_bytes(),original)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],1)
            self.assertEqual((Path(str(unit)+'.d')/'20-chroot-grumble.conf').read_text(),'[Container]\nVolume=isolated:/stores/grumble\n')

    def test_namespace_profile_is_explicit_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,unit=self.fixture(home);original=unit.read_bytes()
            for _ in range(2):subprocess.run(['bash',str(ROOT/'runtime/builder-chroot-profile.sh'),'fixture'],env=env,check=True,capture_output=True)
            self.assertEqual(unit.read_bytes(),original)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],1)
            text=(Path(str(unit)+'.d')/'30-nix-chroot-profile.conf').read_text()
            self.assertEqual(text,'[Container]\nUnmask=/proc/*\n')
            self.assertNotIn('Privileged',text)
            self.assertNotIn('seccomp=unconfined',text)
            self.assertNotIn('SYS_ADMIN',text)

    def test_conflicting_destination_is_rejected_before_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,_=self.fixture(home,conflict=True)
            result=subprocess.run(['bash',str(ROOT/'runtime/chroot-attach.sh'),'fixture','grumble','isolated'],env=env,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],0)


if __name__=='__main__':unittest.main()
