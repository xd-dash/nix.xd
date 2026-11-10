#!/usr/bin/env python3
"""Replace VM1 declaratively, retaining the original guest and store roots."""
from contextlib import ExitStack
import argparse
import base64
import copy
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
from urllib.parse import unquote_to_bytes

from compose_runtime import REPO, run, write_json
from compositions import require
from fatline_host_link import HostLink
from fatline_services import Services
from fatline_recovery import prepare as prepare_recovery
from fatline_reboot import observe, run_gate


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def credentials(root):
    # Paths and hashes are evidence; plaintext credentials never enter controller output.
    paths = list((root/'credentials').rglob('*')) + list((root/'services/credentials').rglob('*'))
    return {str(path.relative_to(root)):digest(path) for path in paths if path.is_file() and path.name not in ('subscriber.json','publisher.json')}


def copy_state(source, destination):
    shutil.copytree(source,destination,dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('controller.lock','*.sock','rebootstrap.json','__pycache__'))


def source_selection(link):
    staged = link.runtime.owner('cat',link.runtime.flake+'/.nix-xd-source-revision')
    require(staged == os.environ.get('NIX_XD_WORKLOAD_REV'),'Stage the selected nix.xd revision first')
    selected = json.loads(link.runtime.owner('nix','eval','--json','--no-write-lock-file',
        link.runtime.flake+'#fatlinePlans.'+os.environ['NIX_XD_SYSTEM']+'.vm1'))['bootstrap']
    require(selected['repository']=='dash-xd/agni' and re.fullmatch(r'[a-f0-9]{40}',selected['revision']) and
        selected['flakeDirectory']=='qemu/coreos-live/local' and selected['package']=='ignitionStarwisp9p','Invalid pinned bootstrap selection')
    return selected


def public_key():
    path=Path(os.environ.get('COREOS_SSH_PUBLIC_KEY') or os.environ['COREOS_SSH_KEY']+'.pub').expanduser()
    key=' '.join(path.read_text().split()[:2])
    require(re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+',key),'Provide the existing Ed25519 public key')
    return key


def choose_port(start, excluded):
    for port in range(start,min(start+32,65536)):
        if port in excluded: continue
        with socket.socket() as listener:
            try: listener.bind(('127.0.0.1',port))
            except OSError: continue
        return port
    raise ValueError('No available replacement SSH port in the selected range')


def ignition_contract(data, key):
    value=json.loads(data)
    users=value.get('passwd',{}).get('users',[])
    require(any(user['name']=='wisp' and key in user.get('sshAuthorizedKeys',[]) for user in users),'Ignition does not bind the expected Wisp public key')
    require(not any(user['name']=='root' and user.get('sshAuthorizedKeys') for user in users),'Root SSH login must not be introduced')
    files=value.get('storage',{}).get('files',[])
    policy=next((item for item in files if item['path']=='/etc/polkit-1/rules.d/60-wisp-reboot.rules'),None)
    require(policy is not None,'Pinned Ignition lacks the narrow reboot policy')
    uri=policy['contents']['source']
    require(uri.startswith('data:'),'Reboot policy must be embedded in Ignition')
    header,payload=uri.split(',',1)
    policy_text=(base64.b64decode(payload) if ';base64' in header else unquote_to_bytes(payload)).decode()
    require('subject.user == "wisp"' in policy_text and 'org.freedesktop.login1.reboot' in policy_text and
        'org.freedesktop.systemd1.manage-units' not in policy_text,'Unexpected reboot policy authority')
    mount=next((item for item in value.get('systemd',{}).get('units',[]) if item['name']=='var-mnt-nixstore.mount'),{})
    require(mount.get('enabled') and 'ro,' in mount.get('contents',''),'Ignition must enable the read-only shared store')


def build_artifacts(link, tx):
    owner=link.runtime.owner
    selected=tx['bootstrap']
    print('FATLINE_REBOOTSTRAP_IGNITION_BUILD='+selected['revision'],flush=True)
    reference='github:dash-xd/agni/'+selected['revision']+'?dir='+selected['flakeDirectory']
    source=owner('nix','eval','--raw','--expr','(builtins.getFlake "'+reference+'").outPath')
    require(re.fullmatch(r'/nix/store/[A-Za-z0-9._+/-]+',source) and source.endswith('/local'),'Unexpected bootstrap source path')
    template=source[:-len('/local')]+'/profiles/starwisp/butane/starwisp-9p.bu'
    anchor='/nix/home/nixuser/.local/state/nix-xd/rebootstrap-'+tx['id']+'-ignition'
    output=owner('env','COREOS_TEST_SSH_PUBLIC_KEY='+tx['publicKey'],'COREOS_STARWISP_BUTANE='+template,
        'COREOS_STARWISP_9P_BUTANE='+template,'nix','build','--impure','--no-write-lock-file','--print-out-paths',
        '--out-link',anchor,reference+'#'+selected['package'])
    require(re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+',output),'Invalid rooted Ignition output')
    data=owner('cat',output+'/config.ign')+'\n'
    ignition_contract(data,tx['publicKey'])
    destination=Path(tx['newBinding']['stateRoot'])/'starwisp'
    destination.mkdir(mode=0o700,parents=True,exist_ok=True)
    old=Path(tx['oldArtifactState'])
    base=destination/'base.qcow2'
    if not base.exists():
        try: os.link(old/'base.qcow2',base)
        except OSError as error:
            if error.errno!=errno.EXDEV: raise
            shutil.copyfile(old/'base.qcow2',base)
    (destination/'config.ign').write_text(data)
    old_manifest=dict(line.split('=',1) for line in (old/'build.txt').read_text().splitlines() if '=' in line)
    (destination/'build.txt').write_text('runner='+old_manifest['runner']+'\ndisk_sha256='+old_manifest['disk_sha256']+
        '\nignition_sha256='+digest(destination/'config.ign')+'\nshared_nix_volume='+tx['storeVolume']+'\n')
    tx['ignitionRoot']={'root':anchor,'output':output,'sha256':digest(destination/'config.ign')}


def candidate_link(original, tx):
    link=copy.deepcopy(original)
    link.root=Path(tx['candidateRoot'])
    link.state_path=link.root/'state.json'
    link.state=json.loads(link.state_path.read_text())
    link.runtime.binding_overrides['vm1']=tx['newBinding']
    link.config=dict(link.config,placement=link.runtime.placement('vm1')[0])
    link.command,link.env=link.runtime.transport_command('vm1','transport')
    return link


def stage_credentials(link):
    incoming=link.state['incoming']
    run(link.command,link.env,True,'install -d -m 700 '+shlex_quote(incoming)+'\n',timeout=30)
    options=['-P' if item=='-p' else item for item in link.command[2:-2]]
    files=[str(link.root/'credentials'/name) for name in ('users.acl','publisher','publisher.json','redis.conf','nginx.conf')]
    run(['scp','-q',*options,*files,link.command[-2]+':'+incoming+'/'],link.env)


def shlex_quote(value):
    import shlex
    return shlex.quote(value)


def restore(link):
    services=Services(link)
    guest_home=run(link.command,link.env,True,'printf %s "$HOME"\n',timeout=30).strip()
    require(re.fullmatch(r'/[A-Za-z0-9/_.-]+',guest_home),'Unexpected guest home')
    link.state['boot']=run(link.command,link.env,True,'cat /proc/sys/kernel/random/boot_id\n',timeout=30).strip()
    link.state['incoming']=guest_home+'/.local/state/nix-xd/incoming-'+link.scope
    stage_credentials(link)
    base=guest_home+'/.local/state/nix-xd/fatline/'+link.scope
    status=run(link.command,link.env,True,'if test -f '+shlex_quote(base+'/prepared')+'; then sha256sum '+shlex_quote(base+'/credentials/users.acl')+' | cut -d " " -f 1; fi\n',timeout=30).strip()
    initial=digest(link.root/'credentials/users.acl')
    require(not status or status in (initial,services.state['aclDigest']),'Replacement ACL does not match retained credentials')
    link.state['aclDigest']=status or initial
    write_json(link.state_path,link.state)
    if not status: link.guest('prepare')
    link.state['status']='prepared'
    write_json(link.state_path,link.state)
    link.guest('start')
    services.execute('activate')
    services.configure_logma()
    prepare_recovery(services,upgrade=True)
    services.execute('qualify')
    return link


def registry_path(link): return REPO/'.state/vm-bindings'/link.runtime.scope/'vm1.json'


def save(tx,path):
    write_json(path,tx)
    print('FATLINE_REBOOTSTRAP_PHASE='+tx['phase']+' transaction='+tx['id'],flush=True)


def retire_original(original, tx):
    # Keep definitions and disk data; stopping the retired runner never releases closure roots.
    body='set -Eeuo pipefail\ntest "$(cat /proc/sys/kernel/random/boot_id)" = '+shlex_quote(tx['before']['boot'])+'\n'
    body+='systemctl --user stop '+' '.join(shlex_quote(original.scope+'-'+role+'.service') for role in ('logma','skymill','nginx','redis'))+'\n'
    retired=json.loads(run(original.runtime.podman+['inspect',tx['oldBinding']['container']],original.env,True,timeout=30))[0]
    require(retired['Id']==tx['oldRunnerId'],'Retired runner identity changed; refusing to stop another container')
    if retired['State']['Running']:
        run(original.command,original.env,True,body,timeout=180)
        run(original.runtime.podman+['stop',tx['oldBinding']['container']],original.env,timeout=120)


def run_rebootstrap(original, peer, plan_only=False):
    require(original.profile=='vm1' and os.environ['NIX_XD_SYSTEM']=='aarch64-linux','Current VM rebootstrap adapter is ARM64 VM1')
    services,peer_services=Services(original),Services(peer)
    require(services.state and services.state['status']=='active' and peer_services.state and peer_services.state['status']=='active','Both Fatline profiles must be active in owner intent')
    pointer=original.root/'rebootstrap.json'
    pending=json.loads(pointer.read_text()) if pointer.exists() else None
    tx_path=Path(pending['transaction']) if pending else None
    tx=json.loads(tx_path.read_text()) if tx_path and tx_path.exists() else None
    fresh=not tx or tx['phase']=='passed'
    if fresh:
        before,peer_before=observe(original),observe(peer)
        require(before['boot']==original.state['boot'] and peer_before['boot']==peer.state['boot'] and before['boot']!=peer_before['boot'],'Guest boot records must match before rebootstrap')
        source=source_selection(original)
        key=public_key()
        port=choose_port(int(os.environ.get('COREOS_REBOOTSTRAP_SSH_PORT','2224')),
            {original.config['placement']['sshPort'],peer.config['placement']['sshPort']})
        if plan_only:
            print('FATLINE_REBOOTSTRAP_PLAN=passed target=vm1 peer=unchanged candidate_ssh_port='+str(port)+' no_guest_root=true',flush=True)
            return
        token=secrets.token_hex(12)
        root=REPO/'.state/rebootstrap'/original.runtime.scope/token
        root.mkdir(mode=0o700,parents=True)
        tx_path=root/'transaction.json'
        archive=root/'original-fatline'
        copy_state(original.root,archive)
        candidate=REPO/'.state/fatline-candidates'/token[:12]
        require(not candidate.exists(),'Candidate state already exists')
        copy_state(archive,candidate)
        candidate_state=json.loads((candidate/'state.json').read_text())
        candidate_state['status']='preparing'
        write_json(candidate/'state.json',candidate_state)
        app_state=json.loads((candidate/'services/state.json').read_text())
        app_state['status']='prepared';app_state.pop('configurationAdapter',None)
        write_json(candidate/'services/state.json',app_state)
        for path in (candidate/'services/reboot-transaction.json',candidate/'services/reboot-qualification.json'):
            path.unlink(missing_ok=True)
        subscriber=json.loads((candidate/'credentials/subscriber.json').read_text())
        subscriber['passwordFile']=str(candidate/'credentials/subscriber')
        write_json(candidate/'credentials/subscriber.json',subscriber)
        old_state=Path(original.env['COREOS_STATE_ROOT'])/'starwisp'
        manifest=dict(line.split('=',1) for line in (old_state/'manifest.txt').read_text().splitlines() if '=' in line)
        logical=original.runtime.plan['placements']['vm1']
        old_binding={'schema':1,'logical':'vm1','baseContainer':logical['container'],
            'container':original.config['placement']['container'],'sshPort':original.config['placement']['sshPort'],
            'stateRoot':original.env['COREOS_STATE_ROOT']}
        new_binding=dict(old_binding,container='coreos-starwisp-r'+token[:12],sshPort=port,stateRoot=str(root/'coreos'))
        recovery_selection=services.selection('servicesRecovery')
        probe_selection=services.selection('servicesProbe')
        owner_id=run(original.runtime.podman+['inspect',original.runtime.scope,'--format','{{.Id}}'],original.env,True,timeout=30).strip()
        tx={'schema':1,'id':token,'phase':'preparing','bootstrap':source,'publicKey':key,'archive':str(archive),
            'candidateRoot':str(candidate),'oldBinding':old_binding,'newBinding':new_binding,
            'oldArtifactState':manifest.get('artifact_state',str(old_state)),
            'before':before,'peerBefore':peer_before,'credentials':credentials(original.root),'ownerId':owner_id,
            'recoverySelection':recovery_selection,'probeSelection':probe_selection,'oldRunnerId':manifest['container_id'],
            'storeVolume':original.env.get('COREOS_NIX_STORE_VOLUME',original.runtime.scope+'-store')}
        save(tx,tx_path)
        write_json(pointer,{'schema':1,'transaction':str(tx_path)})
    else:
        require(not plan_only,'A rebootstrap transaction is pending; resume it with fatline-rebootstrap-local')
        print('FATLINE_REBOOTSTRAP_RESUME='+tx['phase'],flush=True)
    require(services.selection('servicesRecovery')==tx['recoverySelection'] and services.selection('servicesProbe')==tx['probeSelection'] and source_selection(original)==tx['bootstrap'], 'Pending rebootstrap pins different composition inputs')
    original.runtime.binding_overrides['vm1']=tx['oldBinding']
    original.command,original.env=original.runtime.transport_command('vm1','transport')
    services.retain();peer_services.retain()
    require(observe(peer)==tx['peerBefore'],'VM2 changed since preparation')
    if tx['phase']=='preparing':
        build_artifacts(original,tx)
        tx['phase']='prepared';save(tx,tx_path)
    runtime=copy.deepcopy(original.runtime)
    runtime.binding_overrides['vm1']=tx['newBinding']
    env=runtime.environment('transport')
    if tx['phase']=='prepared':
        run(['bash',str(REPO/'bin/nix-xd-coreos-podman'),'start'],env)
        run(['bash',str(REPO/'bin/nix-xd-wisp-ssh')],env)
        tx['phase']='booted';save(tx,tx_path)
    link=candidate_link(original,tx)
    if tx['phase']=='booted':
        restore(link)
        require(credentials(link.root)==tx['credentials'],'Runtime credentials changed during reconstruction')
        tx['phase']='restored';save(tx,tx_path)
    if tx['phase']=='restored':
        receipt=link.root/'services/reboot-qualification.json'
        result=json.loads(receipt.read_text()) if receipt.exists() else {}
        if result.get('result')!='passed': run_gate(link,peer)
        require(observe(peer)==tx['peerBefore'],'VM2 changed during candidate qualification')
        tx['phase']='qualified';save(tx,tx_path)
    if tx['phase']=='qualified':
        receipt=json.loads((link.root/'services/reboot-qualification.json').read_text())
        require(receipt.get('result')=='passed' and observe(link)==receipt['transaction']['after'], 'Candidate changed after reboot qualification')
        require(observe(original)==tx['before'],'Original VM1 changed before cutover')
        require(credentials(link.root)==tx['credentials'],'Candidate credentials changed before cutover')
        tx['phase']='committing';save(tx,tx_path)
    if tx['phase']=='committing':
        copy_state(link.root,original.root)
        subscriber=json.loads((original.root/'credentials/subscriber.json').read_text())
        subscriber['passwordFile']=str(original.root/'credentials/subscriber')
        write_json(original.root/'credentials/subscriber.json',subscriber)
        registry=registry_path(original);registry.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        write_json(registry,dict(tx['newBinding'],transaction=tx['id']))
        tx['phase']='committed';save(tx,tx_path)
    if tx['phase']=='committed':
        retire_original(original,tx)
        tx['phase']='retired';save(tx,tx_path)
    if tx['phase']=='retired':
        require(observe(peer)==tx['peerBefore'],'VM2 changed during cutover')
        require(credentials(original.root)==tx['credentials'],'Active credential hashes differ from the original generation')
        actual=run(original.runtime.podman+['inspect',original.runtime.scope,'--format','{{.Id}}'],original.env,True,timeout=30).strip()
        require(actual==tx['ownerId'],'Authoritative Nix owner changed')
        require(run(original.runtime.podman+['inspect',tx['oldBinding']['container'],'--format','{{.State.Running}}'],original.env,True,timeout=30).strip()=='false','Retired VM is still running')
        tx['after']=observe(link)
        tx['phase']='passed';save(tx,tx_path)
    print('FATLINE_REBOOTSTRAP_RESULT=passed reboot=qualified credentials=preserved roots=retained peer_vm=unchanged archive='+tx['archive'],flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('plan','run'));args=parser.parse_args()
    print('FATLINE_REBOOTSTRAP_START action='+args.action,flush=True)
    require(os.environ.get('NIX_XD_FATLINE_PROFILE','vm1')=='vm1','Only VM1 is replaced')
    os.umask(0o077)
    with ExitStack() as locks:
        previous=dict(os.environ);links=[]
        try:
            for profile in ('vm1','vm2'):
                os.environ.update(NIX_XD_FATLINE_PROFILE=profile,NIX_XD_FATLINE_SCOPE='fatline-arm-'+profile)
                link=HostLink();lock=locks.enter_context((link.root/'controller.lock').open('a'))
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);links.append(link)
        finally:
            os.environ.clear();os.environ.update(previous)
        run_rebootstrap(*links,plan_only=args.action=='plan')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        print('Fatline rebootstrap error: '+str(error),file=sys.stderr);sys.exit(1)
