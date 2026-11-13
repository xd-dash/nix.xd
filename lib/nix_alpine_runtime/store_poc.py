"""Qualify one persistent chroot store alongside the normal local store."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from . import scoped_lock, write_json
from .launch import selected_store, store_options, project_environment


def call(argv, *, check=True, env=None):
    result=subprocess.run(argv,text=True,stdout=subprocess.PIPE,timeout=300,env=env)
    if result.stderr:print(result.stderr,end='',file=sys.stderr,flush=True)
    if check and result.returncode:
        if result.stdout:print(result.stdout,end='',flush=True)
        raise subprocess.CalledProcessError(result.returncode,argv,result.stdout,result.stderr)
    return result


def valid(store,path):
    return call(['nix','path-info','--store',store,path],check=False).returncode==0


def view(path,foreign):
    store=selected_store(os.environ.get('NIX_REMOTE','local'))
    if not valid(store,path) or valid(store,foreign):raise ValueError('Selected execution view has the wrong metadata')
    # The logical store view must expose the unique output, not just its database.
    identity=(Path(path)/'identity').read_text().strip()
    db_path=Path(('' if store=='local' else store)+'/nix/var/nix/db/db.sqlite')
    db=db_path.stat()
    print(json.dumps({'db':[db.st_dev,db.st_ino],'databasePath':str(db_path),
        'path':path,'identity':identity,'foreignValid':False}))



def fixture(bash,tools,system,name):
    script='''set -eu
"$tools/bin/mkdir" -p "$out"
"$tools/bin/date" +%s%N > "$out/start"
"$tools/bin/sleep" 3
"$tools/bin/date" +%s%N > "$out/end"
printf '%s\\n' "$name" > "$out/identity"
'''
    return 'builtins.derivation '+ '{ '+ ' '.join([
        'name='+json.dumps(name)+';', 'system='+json.dumps(system)+';',
        'builder=(builtins.storePath '+json.dumps(bash)+')+"/bin/bash";',
        'tools=builtins.storePath '+json.dumps(tools)+';',
        'args=["-c" '+json.dumps(script)+'];',
        'preferLocalBuild=true;', 'allowSubstitutes=false;',
    ])+' }'




def policy_diagnostics(spec):
    linux=spec.get('linux',{})
    seccomp=linux.get('seccomp',{})
    names={'sethostname','setdomainname','mount','umount','umount2','unshare','setns','clone','clone3','pivot_root','chroot','fsopen','fsconfig','fsmount','move_mount','open_tree','mount_setattr'}
    rules=[]
    for rule in seccomp.get('syscalls',[]):
        matched=sorted(names.intersection(rule.get('names',[])))
        if matched:rules.append({key:value for key,value in dict(rule,names=matched).items() if key in ('names','action','args','errnoRet')})
    process=spec.get('process',{})
    print(json.dumps({'ociPolicy':{'seccompDefaultAction':seccomp.get('defaultAction'),
        'namespaceSyscallRules':rules,'apparmorProfile':process.get('apparmorProfile'),
        'selinuxLabel':process.get('selinuxLabel'),'maskedPaths':linux.get('maskedPaths'),
        'readonlyPaths':linux.get('readonlyPaths'),
        'procMounts':[mount for mount in spec.get('mounts',[]) if mount.get('destination','').startswith('/proc')]}},indent=2,sort_keys=True),flush=True)


def namespace_diagnostics():
    probes={
        'user_mount':['--user','--map-root-user','--mount'],
        'pid_proc':['--user','--map-root-user','--mount','--pid','--fork','--mount-proc'],
        'all_namespaces':['--user','--map-root-user','--mount','--pid','--ipc','--uts','--net','--cgroup','--fork'],
    }
    results={}
    for name,flags in probes.items():
        result=subprocess.run(['unshare',*flags,'true'],text=True,capture_output=True,timeout=15)
        results[name]={'exit':result.returncode,'error':result.stderr.strip()}
    status={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.split(':',1)[0] in ('Seccomp','NoNewPrivs','CapEff','CapBnd'):
            key,value=line.split(':',1);status[key]=value.strip()
    limits={}
    for name in ('max_user_namespaces','max_mnt_namespaces','max_pid_namespaces','max_cgroup_namespaces'):
        path=Path('/proc/sys/user')/name
        if path.exists():limits[name]=path.read_text().strip()
    temporary=subprocess.run(['unshare','--user','--map-root-user','--mount','--fork','sh','-ec',
        "d=$(mktemp -d); trap 'rmdir \"$d\"' EXIT; mount -t tmpfs tmpfs \"$d\"; umount \"$d\""],
        text=True,capture_output=True,timeout=15)
    results['mount_tmpfs']={'exit':temporary.returncode,'error':temporary.stderr.strip()}
    result={'probes':results,'process':status,'limits':limits}
    print(json.dumps(result,indent=2,sort_keys=True),flush=True)
    print('CHROOT_NAMESPACE_DIAGNOSTIC=collected security_changes=false',flush=True)
    return result



def view_command(store,flake,system,path,foreign):
    return ['nix','run',*store_options(store),'--no-write-lock-file',
        flake+'#apps.'+system+'.store-poc-view','--','view','--path',path,'--foreign',foreign]


def qualify(root,flake,system):
    selected_store(root)
    if root=='local':raise ValueError('Select an isolated chroot store for this POC')
    target=Path(root)
    if not target.is_mount() or not (target/'.nix-xd-chroot-v1').is_file():
        raise ValueError('Attach the persistent chroot volume first')
    if os.geteuid()==0:raise ValueError('Use the ordinary Nix-Alpine executor')
    os.environ['NIX_REMOTE']='local'
    # Never silently weaken seccomp or change kernel namespace policy.
    capabilities=namespace_diagnostics()
    if any(probe['exit'] for probe in capabilities['probes'].values()):
        raise ValueError('Required sandbox namespace probes failed; no builds or security changes performed')
    state=target/'.poc';state.mkdir(mode=0o700,exist_ok=True)
    with scoped_lock(state/'controller.lock'):
        token=secrets.token_hex(8)
        evidence=state/(token+'.json')
        receipt={'result':'running','root':root,'id':token,'authoritativeGc':False}
        write_json(evidence,receipt)
        try:
            print('CHROOT_POC_PREPARE=starting',flush=True)
            paths=json.loads(call(['nix','build','--store','local','--no-write-lock-file','--no-link','--json',flake+'#storePocTools']).stdout)[0]['outputs']['out']
            tools_meta=json.loads((Path(paths)/'tools.json').read_text())
            # Copy only the declared fixture tool closures, not either store's database.
            call(['nix','copy','--no-check-sigs','--from','local','--to',root,tools_meta['bash'],tools_meta['coreutils'],tools_meta['view']])
            stores={'normal':'local','chroot':root}
            drvs={role:call(['nix-instantiate','--store',store,'--expr',fixture(tools_meta['bash'],tools_meta['coreutils'],system,'nix-xd-poc-'+role+'-'+token)]).stdout.strip() for role,store in stores.items()}
            roots={role:state/(token+'-'+role+'-root') for role in stores}
            print('CHROOT_POC_BUILDS=concurrent',flush=True)
            def build(role):
                call(['nix-store',*store_options(stores[role]),'--realise',drvs[role],'--add-root',str(roots[role]),'--indirect'])
                return call(['nix-store','--store',stores[role],'--query','--outputs',drvs[role]]).stdout.strip()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures={role:pool.submit(build,role) for role in stores}
                outputs={role:future.result() for role,future in futures.items()}
            physical={'normal':Path(outputs['normal']),'chroot':target/outputs['chroot'].lstrip('/')}
            intervals={role:[int((path/name).read_text()) for name in ('start','end')] for role,path in physical.items()}
            if max(value[0] for value in intervals.values())>=min(value[1] for value in intervals.values()):
                raise ValueError('Build intervals did not overlap; rerun the bounded POC')
            if not valid('local',outputs['normal']) or valid('local',outputs['chroot']):raise ValueError('Normal metadata is not isolated')
            if not valid(root,outputs['chroot']) or valid(root,outputs['normal']):raise ValueError('Chroot metadata is not isolated')
            dbs={role:Path(prefix+'/nix/var/nix/db/db.sqlite').stat() for role,prefix in {'normal':'','chroot':root}.items()}
            identities={role:[stat.st_dev,stat.st_ino] for role,stat in dbs.items()}
            if identities['normal']==identities['chroot']:raise ValueError('Stores use the same database')
            views={role:json.loads(call(view_command(store,flake,system,outputs[role],outputs['chroot' if role=='normal' else 'normal']),env=project_environment(os.environ,store)).stdout) for role,store in stores.items()}
            for role in stores:
                if views[role]['db']!=identities[role]:raise ValueError('Execution queried the wrong metadata database')
                if views[role]['identity']!='nix-xd-poc-'+role+'-'+token:raise ValueError('Execution read the wrong logical output')
            print('CHROOT_POC_VIEW=passed metadata=separate nested_nix=selected',flush=True)
            print('CHROOT_POC_ROOTS=check_protected_output',flush=True)
            if call(['nix-store','--store',root,'--delete',outputs['chroot']],check=False).returncode==0:
                raise ValueError('Chroot rooted output was unexpectedly deleted')
            if not valid(root,outputs['chroot']):raise ValueError('Rooted output was lost')
            # Delete only this POC's unique output after releasing its own root.
            roots['chroot'].unlink()
            call(['nix-store','--store',root,'--delete',outputs['chroot']])
            if valid(root,outputs['chroot']) or not valid('local',outputs['normal']):raise ValueError('Per-store retention failed')
            roots['normal'].unlink()
            receipt.update(result='passed',outputs=outputs,intervals=intervals,databases=identities,
                concurrentBuilds=True,executionViews=True,rootRetention=True)
            print('CHROOT_STORE_POC_RESULT=passed concurrent=true metadata=separate retention=separate view=chroot authoritative_gc=false',flush=True)
        except (OSError,ValueError,subprocess.SubprocessError):
            receipt['result']='failed';raise
        finally:
            write_json(evidence,receipt)
            print('CHROOT_POC_EVIDENCE='+str(evidence),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('qualify','view','diagnose'))
    parser.add_argument('--policy',action='store_true')
    parser.add_argument('--root')
    parser.add_argument('--flake')
    parser.add_argument('--system')
    parser.add_argument('--path')
    parser.add_argument('--foreign')
    args=parser.parse_args()
    if args.action=='diagnose':
        if args.policy:policy_diagnostics(json.load(sys.stdin))
        namespace_diagnostics()
    elif args.action=='view':view(args.path,args.foreign)
    else:
        if not args.root or not args.flake or args.system not in ('aarch64-linux','x86_64-linux'):
            raise ValueError('Provide root, flake and supported system')
        qualify(args.root,args.flake,args.system)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Chroot POC error: '+str(error),file=sys.stderr);sys.exit(1)
