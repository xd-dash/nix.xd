"""Launch a project's flake app inside the selected Linux builder."""
import argparse
import json
import os
import platform
import re
import sys


def selected_store(value):
    if value=='local':return value
    if not re.fullmatch(r'/stores/[a-z][a-z0-9-]{0,39}',value):
        raise ValueError('PROJECT_STORE must be local or /stores/<name>')
    return value


def store_options(store):
    store=selected_store(store)
    options=['--store',store]
    if store!='local':options+=['--option','sandbox','true','--option','sandbox-fallback','false']
    return options


def command(flake, app, system, arguments, store='local'):
    if not flake or flake.startswith('-') or '#' in flake or any(c in flake for c in ('\n','\r','\x00')):
        raise ValueError('Expected a project flake reference without an output fragment')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',app):raise ValueError('Invalid project app')
    if system not in ('aarch64-linux','x86_64-linux'):raise ValueError('Unsupported project system')
    values=json.loads(arguments)
    if not isinstance(values,list) or not all(isinstance(value,str) and '\x00' not in value for value in values):
        raise ValueError('PROJECT_ARGS_JSON must be a JSON array of strings')
    return ['nix','run',*store_options(store),'--no-write-lock-file',flake+'#apps.'+system+'.'+app,'--',*values]



def project_environment(base,store):
    store=selected_store(store)
    env=dict(base,NIX_REMOTE=store,NIX_XD_PROJECT_PHYSICAL_STORE=store)
    if store!='local':env['NIX_CONFIG']=env.get('NIX_CONFIG','')+'\nsandbox = true\nsandbox-fallback = false\n'
    return env


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--flake',required=True)
    parser.add_argument('--app',required=True)
    parser.add_argument('--system',required=True)
    parser.add_argument('--args-json',default='[]')
    parser.add_argument('--store',default='local')
    args=parser.parse_args()
    if platform.system()!='Linux':raise ValueError('Project orchestration must run inside Nix-Alpine')
    store=selected_store(args.store)
    if store!='local':
        from pathlib import Path
        if not Path(store).is_mount() or not (Path(store)/'.nix-xd-chroot-v1').is_file():
            raise ValueError('Selected chroot store must be an attached persistent volume')
    argv=command(args.flake,args.app,args.system,args.args_json,store)
    # Nix's runtime store mount does not redirect its metadata directories.
    os.environ.update(project_environment(os.environ,store))
    print('PROJECT_EXECUTOR=linux app='+args.app+' system='+args.system,flush=True)
    os.execvp(argv[0],argv)


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:print('Project launch error: '+str(error),file=sys.stderr);sys.exit(2)
