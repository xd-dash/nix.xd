"""Scoped syscall policy for a trusted nested Nix builder."""
import argparse
import copy
import json
import os
import socket
import subprocess
import sys

UTS_CALLS={'sethostname','setdomainname'}


def render(spec):
    policy=copy.deepcopy(spec.get('linux',{}).get('seccomp'))
    if not isinstance(policy,dict) or policy.get('defaultAction')!='SCMP_ACT_ERRNO':
        raise ValueError('Expected an existing restrictive seccomp policy')
    rules=[]
    for rule in policy.get('syscalls',[]):
        names=[name for name in rule['names'] if name not in UTS_CALLS]
        if names:rules.append(dict(rule,names=names))
    rules.append({'names':sorted(UTS_CALLS),'action':'SCMP_ACT_ALLOW'})
    policy['syscalls']=rules
    return policy


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('render','probe'))
    args=parser.parse_args()
    if args.action=='render':
        json.dump(render(json.load(sys.stdin)),sys.stdout,indent=2,sort_keys=True);print()
    else:
        if os.geteuid()==0:raise ValueError('Run the probe as the ordinary builder user')
        before=socket.gethostname()
        code='import socket; socket.sethostname(b"nix-chroot-probe"); assert socket.gethostname()=="nix-chroot-probe"'
        subprocess.run(['unshare','--user','--map-root-user','--uts','--fork',sys.executable,'-c',code],check=True,timeout=20)
        if socket.gethostname()!=before:raise ValueError('Probe changed the outer hostname')
        print('BUILDER_UTS_PROBE=passed private=true')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print('Builder policy error: '+str(error),file=sys.stderr);sys.exit(1)
