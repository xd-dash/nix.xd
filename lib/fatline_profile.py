#!/usr/bin/env python3
"""Apply one Agni startup profile, qualify it, and select its generation."""
from contextlib import ExitStack
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys

from compose_runtime import REPO, run, write_json
from compositions import require
from fatline_host_link import HostLink
from fatline_services import Services
from fatline_rebootstrap import copy_state, credentials
from fatline_reboot import observe
from fatline_logmash import qualify as qualify_subscriber
from fatline_generations import activate


def selected(link):
    owner=link.runtime.owner
    require(owner('cat',link.runtime.flake+'/.nix-xd-source-revision')==os.environ['NIX_XD_WORKLOAD_REV'],'Stage the selected revision first')
    plan=json.loads(owner('nix','eval','--json','--no-write-lock-file',link.runtime.flake+'#fatlinePlans.'+os.environ['NIX_XD_SYSTEM']+'.'+link.profile))
    source=plan['startupProfile']
    require(source['repository']=='dash-xd/agni' and re.fullmatch(r'[a-f0-9]{40}',source['revision']) and
        source['package']=='coreos-startup-profile' and source['contract']=='coreos-startup-profile-v1','Invalid startup profile source')
    return source


def invoke(link, record, action, incoming=None):
    script='/var/mnt/nixstore/'+record['bundle'].removeprefix('/nix/store/')+'/runtime.sh'
    command=['bash',script,action,link.scope,incoming or record['probe']]
    body='set -Eeuo pipefail\ntest "$(cat /proc/sys/kernel/random/boot_id)" = '+shlex.quote(link.state['boot'])+'\n'
    body+='test "$(sha256sum '+shlex.quote(script)+' | cut -d " " -f 1)" = '+shlex.quote(record['sha256'])+'\n'
    if incoming:
        body+='test "$(sha256sum '+shlex.quote(incoming+'/manifest.json')+' | cut -d " " -f 1)" = '+shlex.quote(record['manifestDigest'])+'\n'
    output=run(link.command,link.env,True,body+shlex.join(command)+'\n',timeout=1200)
    print(output,end='',flush=True)
    expected={'install':'FATLINE_STARTUP_PROFILE=passed','status':'FATLINE_STARTUP_PROFILE_STATUS=passed',
        'qualify-reliability':'FATLINE_PROFILE_RELIABILITY=passed bootstrap_failure=blocked redis_crash=automatic boot=unchanged',
        'recover':'FATLINE_PROFILE_RECOVERY=passed'}[action]
    require(expected in output.splitlines(),'Startup profile acknowledgement missing; edit and rerun, roots retained')


def apply_profile(link, record):
    home=record['spec']['home']
    incoming=home+'/.local/state/nix-xd/incoming-profile-'+record['generation']
    run(link.command,link.env,True,'install -d -m 700 '+shlex.quote(incoming)+'\n',timeout=30)
    options=['-P' if item=='-p' else item for item in link.command[2:-2]]
    rendered=link.root/'startup-rendered'
    files=[str(path) for path in rendered.iterdir() if path.is_file()]
    files+=[str(link.root/'services/credentials'/name) for name in ('logma','skymill','bootstrap','users.acl')]
    run(['scp','-q','-r',*options,*files,link.command[-2]+':'+incoming+'/'],link.env)
    invoke(link,record,'install',incoming)


def restore_profile(link):
    """Cold VM reconstruction uses the same profile; no configure/recovery phases."""
    path=link.root/'services/startup-profile.json'
    record=json.loads(path.read_text())
    record['spec']['home']=run(link.command,link.env,True,'printf %s "$HOME"\n',timeout=30).strip()
    require(re.fullmatch(r'/[A-Za-z0-9/_.-]+',record['spec']['home']),'Invalid guest home')
    record['spec']['port']=link.config['ingress']['guestProxyPort']
    write_json(link.root/'startup-spec.json',record['spec'])
    run([sys.executable,str(link.root/'startup-render.py'),str(link.root/'startup-spec.json'),str(link.root/'startup-rendered')],link.env)
    record['manifestDigest']=hashlib.sha256((link.root/'startup-rendered/manifest.json').read_bytes()).hexdigest()
    write_json(path,record)
    apply_profile(link,record)
    record['boot']=link.state['boot'];record['status']='installed';write_json(path,record)
    services=Services(link);services.state['status']='active';write_json(services.path,services.state)
    link.state['aclDigest']=services.state['aclDigest'];write_json(link.state_path,link.state)


def run_profile(original,peer):
    source=selected(original)
    require((original.root/'generation.json').exists(),'Select the existing sandbox generation before changing its startup profile')
    services=Services(original)
    require(services.state and services.state['status']=='active','Services must have an active declared generation')
    pointer=original.control_root/'profile-operation.json'
    operation=json.loads(pointer.read_text()) if pointer.exists() else None
    if not operation or operation['source']!=source or operation['phase']=='passed':
        existing=services.root/'startup-profile.json'
        if existing.exists() and json.loads(existing.read_text())['source']==source:
            try:
                invoke(original,json.loads(existing.read_text()),'status')
            except (ValueError,subprocess.SubprocessError):
                print('FATLINE_PROFILE_REAPPLY=service_not_ready',flush=True)
            else:
                print('FATLINE_PROFILE_RESULT=reused',flush=True);return
        before={'boot':run(original.command,original.env,True,'cat /proc/sys/kernel/random/boot_id\n',timeout=30).strip()}
        peer_before=observe(peer)
        require(before['boot']==original.state['boot'] and peer_before['boot']==peer.state['boot'],'Boot records must match before profile apply')
        token=secrets.token_hex(12)
        root=REPO/'.state/fatline-candidates'/token[:12]
        copy_state(original.root,root)
        for name in ('generation.json','services/generation-qualification.json','services/reboot-qualification.json','services/reboot-transaction.json'):
            (root/name).unlink(missing_ok=True)
        subscriber=json.loads((root/'credentials/subscriber.json').read_text());subscriber['passwordFile']=str(root/'credentials/subscriber');write_json(root/'credentials/subscriber.json',subscriber)
        operation={'id':token,'source':source,'root':str(root),'phase':'preparing','before':before,'peerBefore':peer_before,'credentials':credentials(original.root)}
        write_json(pointer,operation)
    link=copy.deepcopy(original);link.root=Path(operation['root']);link.state_path=link.root/'state.json';link.state=json.loads(link.state_path.read_text())
    require(observe(peer)==operation['peerBefore'],'VM2 changed during profile operation')
    Services(link).retain()
    if operation['phase']=='preparing':
        anchor='/nix/home/nixuser/.local/state/nix-xd/startup-'+link.scope+'-'+source['revision']+'-'+operation['id']
        bundle=link.runtime.owner('nix','build','--no-write-lock-file','--print-out-paths','--out-link',anchor,
            'github:dash-xd/agni/'+source['revision']+'?dir=local/fatline#'+source['package'])
        require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+',bundle),'Invalid startup profile output')
        metadata=json.loads(link.runtime.owner('cat',bundle+'/metadata.json'))
        for key in ('schema','logmaRev','skymillRev','ratelimiterRev'):
            require(metadata[key]==services.state['metadata'][key],'Profile changes application component revisions')
        home=run(link.command,link.env,True,'printf %s "$HOME"\n',timeout=30).strip()
        require(re.fullmatch(r'/[A-Za-z0-9/_.-]+',home),'Invalid guest home')
        spec={'schema':1,'scope':link.scope,'home':home,'bundle':bundle,'port':link.config['ingress']['guestProxyPort'],
            'archive':link.state['archive'],'redis':link.state['metadata']['redis']+'/bin/redis-server',
            'nginx':link.state['metadata']['nginx']+'/bin/nginx','logma':services.state['metadata']['logma'],
            'skymill':services.state['metadata']['skymill'],'probe':metadata['probe'],'aclDigest':services.state['aclDigest']}
        for name in ('render.py','runtime.sh'):
            (link.root/('startup-'+name)).write_text(link.runtime.owner('cat',bundle+'/'+name)+'\n')
        write_json(link.root/'startup-spec.json',spec)
        run([sys.executable,str(link.root/'startup-render.py'),str(link.root/'startup-spec.json'),str(link.root/'startup-rendered')],link.env)
        dependencies=[]
        for name in ('redis','nginx','logma','skymill','archive'):
            store_path='/'.join(spec[name].split('/')[:4])
            dep_root=anchor+'-'+name
            link.runtime.owner('nix-store','--realise','--add-root',dep_root,store_path)
            dependencies.append({'root':dep_root,'bundle':store_path})
        record={'dependencies':dependencies,'status':'prepared','boot':link.state['boot'],'source':source,'root':anchor,'bundle':bundle,'probe':metadata['probe'],'script':'runtime.sh',
            'sha256':hashlib.sha256((link.root/'startup-runtime.sh').read_bytes()).hexdigest(),
            'generation':operation['id'],'spec':spec,
            'manifestDigest':hashlib.sha256((link.root/'startup-rendered/manifest.json').read_bytes()).hexdigest()}
        write_json(link.root/'services/startup-profile.json',record)
        operation['phase']='applying';write_json(pointer,operation)
    record=json.loads((link.root/'services/startup-profile.json').read_text())
    if operation['phase']=='applying':
        print('FATLINE_PROFILE_APPLY=starting scope='+link.scope+' ephemeral_redis_restart=true',flush=True)
        apply_profile(link,record)
        record['status']='installed'
        write_json(link.root/'services/startup-profile.json',record)
        operation['phase']='qualifying';write_json(pointer,operation)
    if operation['phase']=='qualifying':
        Services(link).retain()
        Services(link).execute('qualify')
        qualify_subscriber(link,resource=True)
        after=observe(link)
        require(after['boot']==operation['before']['boot'],'Guest rebooted during profile application')
        require(observe(peer)==operation['peerBefore'],'VM2 changed during profile application')
        require(credentials(link.root)==operation['credentials'],'Profile changed credential bytes')
        receipt={'result':'passed','observation':after,'gates':{'services':True,'hostSubscriber':True,'reboot':False}}
        write_json(link.root/'services/generation-qualification.json',receipt)
        previous=json.loads((original.root/'generation.json').read_text())
        physical=original.runtime.placement(original.profile)[0]
        binding={'schema':1,'logical':original.profile,'baseContainer':original.runtime.plan['placements'][original.profile]['container'],
            'container':physical['container'],'sshPort':physical['sshPort'],'stateRoot':link.env['COREOS_STATE_ROOT']}
        tx={'id':operation['id'],'newBinding':binding,'storeVolume':previous['store']['volume'],
            'bootstrap':previous['sources']['bootstrap'],'credentials':operation['credentials']}
        activate(link,tx,receipt)
        operation['phase']='passed';write_json(pointer,operation)
    print('FATLINE_PROFILE_RESULT=passed reboot=not_run peer_vm=unchanged',flush=True)



def run_reliability(link,peer,action):
    services=Services(link)
    path=services.root/'startup-profile.json'
    require(path.exists(),'Apply fatline-profile-local first')
    record=json.loads(path.read_text())
    require(record['status']=='installed' and record['source']==selected(link),'Apply the selected startup profile first')
    require(record['boot']==link.state['boot'],'Reconcile the guest boot before service recovery')
    peer_before=observe(peer)
    before_boot=run(link.command,link.env,True,'cat /proc/sys/kernel/random/boot_id\n',timeout=30).strip()
    require(before_boot==link.state['boot'],'Guest boot record changed')
    credential_hashes=credentials(link.root)
    services.retain();Services(peer).retain()
    evidence=services.root/('reliability-qualification.json' if action=='qualify-reliability' else 'profile-recovery.json')
    receipt={'result':'running','source':record['source'],'boot':before_boot,'fullFatline':False,
        'persistence':'ephemeral','rebootQualified':False,'parentVmReplacementQualified':False}
    write_json(evidence,receipt)
    try:
        invoke(link,record,action)
        services.execute('qualify')
        qualify_subscriber(link,resource=True)
        after=observe(link)
        require(after['boot']==before_boot,'Guest rebooted during application reliability gate')
        require(observe(peer)==peer_before,'VM2 changed during application reliability gate')
        require(credentials(link.root)==credential_hashes,'Application reliability gate changed credentials')
        receipt.update(result='passed',observation=after,peerUnchanged=True,
            bootstrapFailureQualified=action=='qualify-reliability',redisCrashQualified=action=='qualify-reliability')
    except (ValueError,OSError,subprocess.SubprocessError):
        receipt['result']='failed'
        from fatline_recovery import diagnose
        try:diagnose(services)
        except (OSError,subprocess.SubprocessError) as error:print('Diagnostics unavailable: '+str(error),file=sys.stderr)
        raise
    finally:write_json(evidence,receipt)
    print('FATLINE_PROFILE_'+('RELIABILITY' if action=='qualify-reliability' else 'RECOVERY')+'_RESULT=passed peer_vm=unchanged',flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',nargs='?',default='apply',choices=('apply','qualify-reliability','recover'))
    action=parser.parse_args().action
    print('FATLINE_PROFILE_START='+action,flush=True)
    require(os.environ.get('NIX_XD_FATLINE_PROFILE','vm1')=='vm1','Qualify VM1 startup profile first')
    os.umask(0o077)
    with ExitStack() as locks:
        saved=dict(os.environ);links=[]
        try:
            for profile in ('vm1','vm2'):
                os.environ.update(NIX_XD_FATLINE_PROFILE=profile,NIX_XD_FATLINE_SCOPE='fatline-arm-'+profile)
                link=HostLink();lock=locks.enter_context(link.lock_path.open('a'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);links.append(link)
        finally:os.environ.clear();os.environ.update(saved)
        if action=='apply':run_profile(*links)
        else:run_reliability(*links,action)


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        print('Fatline profile error: '+str(error),file=sys.stderr);sys.exit(1)
