"""Resolved sandbox generations and a single atomic activation record."""
import json
from pathlib import Path
from compose_runtime import REPO, write_json
from compositions import require


def active_root(owner, profile, fallback):
    path=REPO/'.state/vm-bindings'/owner/(profile+'.json')
    if not path.exists(): return fallback
    binding=json.loads(path.read_text())
    if 'fatlineRoot' not in binding: return fallback
    require(binding.get('schema')==1 and binding.get('logical')==profile,'Invalid generation activation record')
    root=Path(binding['fatlineRoot'])
    require(root.is_absolute() and root.is_dir() and (root/'state.json').is_file(),'Active generation state is missing')
    manifest_path=root/'generation.json'
    require(manifest_path.is_file(),'Active generation manifest is missing')
    manifest=json.loads(manifest_path.read_text())
    require(manifest.get('schema')==1 and manifest['id']==binding['generation'] and
        manifest['owner']==owner and manifest['logical']==profile and
        manifest['guest']=={key:binding[key] for key in ('container','sshPort','stateRoot')},'Generation manifest and activation record differ')
    return root


def qualification(receipt):
    require(receipt.get('result')=='passed','Generation qualification failed')
    if 'transaction' in receipt:
        return {'observation':receipt['transaction']['after'],
            'gates':{'services':True,'hostSubscriber':True,'reboot':True}}
    require(receipt.get('gates',{}).get('services') and receipt['gates'].get('hostSubscriber'),
        'Generation lacks service or host subscriber qualification')
    return {'observation':receipt['observation'],'gates':receipt['gates']}


def resolve_manifest(link, tx, receipt):
    proof=qualification(receipt)
    services=json.loads((link.root/'services/state.json').read_text())
    startup=json.loads((link.root/'services/recovery.json').read_text())
    return {'schema':1,'id':tx['id'],'owner':link.runtime.scope,'logical':link.profile,
        'scope':link.scope,'system':link.state['plan']['system'],
        'guest':{key:tx['newBinding'][key] for key in ('container','sshPort','stateRoot')},
        'store':{'volume':tx['storeVolume'],'guestAccess':'read-only','rootfs':link.state['archive']},
        'sources':{'bootstrap':tx['bootstrap'],'transport':{'revision':link.state['agniRev'],
            'adapter':link.state.get('guestAdapter')},'services':services['source'],
            'probe':services.get('qualificationProbe'),'startup':startup['source']},
        'outputs':{'transport':link.state['bundle'],'services':services['bundle'],'startup':startup['bundle']},
        'credentials':{'location':'generation-local-private-files','hashes':tx['credentials']},
        'qualification':{'boot':proof['observation']['boot'],'gates':proof['gates'],'fullFatline':False}}


def activate(link, tx, receipt):
    """Select existing qualified state without merging generations or contacting the old guest."""
    proof=qualification(receipt)
    require(proof['observation']['boot']==link.state['boot'], 'Generation has no matching boot qualification')
    manifest=resolve_manifest(link,tx,receipt)
    target=link.root/'generation.json'
    if target.exists():
        require(json.loads(target.read_text())==manifest,'Generation manifest changed; create a new generation')
    else: write_json(target,manifest)
    binding=dict(tx['newBinding'],fatlineRoot=str(link.root),generation=tx['id'],transaction=tx['id'])
    registry=REPO/'.state/vm-bindings'/link.runtime.scope/(link.profile+'.json')
    registry.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    write_json(registry,binding)
    return binding
