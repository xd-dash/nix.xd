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
        (home/'oci.json').write_text(json.dumps({'linux':{'seccomp':{'defaultAction':'SCMP_ACT_ERRNO','syscalls':[]}}}))
        (home/'state').write_text(json.dumps({'attached':False,'conflict':conflict,'restarts':0,'profile':False,'labelDisabled':False,'probeExit':0}))
        mock=tools/'podman';mock.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['HOME'])/'state';state=json.loads(p.read_text());a=sys.argv[1:]
if a[0]=='info':print('true')
elif a[:2]==['ps','-aq']:print('owner')
elif a[0]=='inspect':
 f=a[-1]
 if 'OCIConfigPath' in f:print(str(p.parent/'oci.json'))
 elif 'ProcessLabel' in f:
  if not state['labelDisabled']:print('system_u:system_r:container_t:s0:c1,c2')
 elif 'Privileged' in f:print('false')
 elif 'MaskedPaths' in f:
  if not state['profile']:print('/proc/kcore\\n/proc/sys')
 elif 'State.Running' in f:print('true')
 elif '.Image' in f:print('sha256:fixture')
 elif '.Name'==f.strip('{}'):print('fixture')
 elif 'if eq .Destination' in f:print('authoritative')
 elif '.RW' in f:
  if state['attached']:print('isolated /stores/grumble true')
 else:
  print('authoritative|/nix')
  if state['conflict']:print('other|/stores/grumble')
  elif state['attached']:print('isolated|/stores/grumble')
elif a[0]=='volume':sys.exit(0)
elif a[0]=='exec':
 if 'build' in a:print('/nix/store/'+'a'*32+('-nix-xd-builder-policy' if 'builderPolicy' in a[-1] else '-nix-xd-proc-probe'))
 if a[-1]=='render':
  from nix_alpine_runtime.builder_policy import render
  print(json.dumps(render(json.load(sys.stdin)),indent=2,sort_keys=True))
 if a[-1]=='/proc/self/mountinfo' and not state['profile']:print('/proc/sys')
elif a[0]=='run':
 if any('/bin/nix-xd-proc-probe' in arg for arg in a):
  sys.exit(state['probeExit'] if 'label=disable' in a else 1)
else:raise SystemExit('Unexpected '+repr(a))
''');mock.chmod(0o755)
        mock=tools/'systemctl';mock.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['HOME'])/'state';s=json.loads(p.read_text())
if 'show' in sys.argv:print('loaded')
if 'restart' in sys.argv:
 s.update(labelDisabled=(Path(os.environ['HOME'])/'.config/containers/systemd/fixture.container.d/31-nix-chroot-selinux.conf').exists(),attached=True,restarts=s['restarts']+1,profile=(Path(os.environ['HOME'])/'.config/containers/systemd/fixture.container.d/30-nix-chroot-profile.conf').exists());p.write_text(json.dumps(s))
''');mock.chmod(0o755)
        # The runtime executes on Linux, where flock and sha256sum are present.
        # Static tests on macOS mock those platform tools without changing production policy.
        mock=tools/'flock';mock.write_text('#!/usr/bin/env bash\nexit 0\n');mock.chmod(0o755)
        mock=tools/'sha256sum';mock.write_text('''#!/usr/bin/env python3
import hashlib,sys
for name in sys.argv[1:]:
 with open(name,'rb') as source:
  print(hashlib.sha256(source.read()).hexdigest()+'  '+name)
''');mock.chmod(0o755)
        return dict(os.environ,HOME=str(home),PATH=str(tools)+':'+os.environ['PATH'],PYTHONPATH=str(ROOT/'lib')),unit

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

    def test_selinux_profile_requires_successful_controlled_comparison(self):
        for probe_exit in (0,1):
            with self.subTest(probe_exit=probe_exit),tempfile.TemporaryDirectory() as directory:
                home=Path(directory);env,unit=self.fixture(home)
                state=json.loads((home/'state').read_text());state.update(attached=True,profile=True,probeExit=probe_exit);(home/'state').write_text(json.dumps(state))
                result=subprocess.run(['bash',str(ROOT/'runtime/builder-chroot-profile.sh'),'fixture','/workspaces/runtime','disabled'],env=env,capture_output=True,text=True)
                changed=probe_exit==0
                self.assertEqual(result.returncode==0,changed,result.stderr)
                file=Path(str(unit)+'.d')/'31-nix-chroot-selinux.conf'
                self.assertEqual(file.exists(),changed)
                self.assertEqual(json.loads((home/'state').read_text())['restarts'],int(changed))
                if changed:self.assertEqual(file.read_text(),'[Container]\nSecurityLabelDisable=true\n')

    def test_syscall_profile_is_scoped_and_does_not_restart_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,unit=self.fixture(home);original=unit.read_bytes()
            for _ in range(2):subprocess.run(['bash',str(ROOT/'runtime/builder-chroot-syscalls.sh'),'fixture','/workspaces/runtime'],env=env,check=True,capture_output=True)
            self.assertEqual(unit.read_bytes(),original)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],1)
            policy=json.loads((home/'.config/nix-xd/seccomp/fixture-nix-chroot.json').read_text())
            self.assertEqual(policy['defaultAction'],'SCMP_ACT_ERRNO')
            self.assertEqual(policy['syscalls'],[{'action':'SCMP_ACT_ALLOW','names':['setdomainname','sethostname']}])

    def test_conflicting_destination_is_rejected_before_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);env,_=self.fixture(home,conflict=True)
            result=subprocess.run(['bash',str(ROOT/'runtime/chroot-attach.sh'),'fixture','grumble','isolated'],env=env,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(json.loads((home/'state').read_text())['restarts'],0)


if __name__=='__main__':unittest.main()
