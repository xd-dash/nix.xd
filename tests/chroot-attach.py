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
        (home/'state').write_text(json.dumps({'attached':False,'conflict':conflict,'restarts':0}))
        mock=tools/'podman';mock.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['HOME'])/'state';state=json.loads(p.read_text());a=sys.argv[1:]
if a[0]=='info':print('true')
elif a[:2]==['ps','-aq']:print('owner')
elif a[0]=='inspect':
 f=a[-1]
 if 'State.Running' in f:print('true')
 elif '.Image' in f:print('sha256:fixture')
 elif '.Name'==f.strip('{}'):print('fixture')
 elif '.RW' in f:
  if state['attached']:print('isolated /stores/grumble true')
 else:
  print('authoritative|/nix')
  if state['conflict']:print('other|/stores/grumble')
  elif state['attached']:print('isolated|/stores/grumble')
elif a[0]=='volume':sys.exit(0)
elif a[0] in ('run','exec'):pass
else:raise SystemExit('Unexpected '+repr(a))
''');mock.chmod(0o755)
        mock=tools/'systemctl';mock.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['HOME'])/'state';s=json.loads(p.read_text())
if 'show' in sys.argv:print('loaded')
if 'restart' in sys.argv:s.update(attached=True,restarts=s['restarts']+1);p.write_text(json.dumps(s))
''');mock.chmod(0o755)
        return dict(os.environ,HOME=str(home),PATH=str(tools)+':'+os.environ['PATH']),unit

    def test_adds_only_dropin_and_second_apply_reuses_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,unit=self.fixture(home);original=unit.read_bytes()
            for _ in range(2):subprocess.run(['bash',str(ROOT/'runtime/chroot-attach.sh'),'fixture','grumble','isolated'],env=env,check=True,capture_output=True)
            self.assertEqual(unit.read_bytes(),original)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],1)
            self.assertEqual((Path(str(unit)+'.d')/'20-chroot-grumble.conf').read_text(),'[Container]\nVolume=isolated:/stores/grumble\n')

    def test_conflicting_destination_is_rejected_before_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,_=self.fixture(home,conflict=True)
            result=subprocess.run(['bash',str(ROOT/'runtime/chroot-attach.sh'),'fixture','grumble','isolated'],env=env,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],0)


if __name__=='__main__':unittest.main()
