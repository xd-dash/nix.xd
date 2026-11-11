"""Launch a project's flake app inside the selected Linux builder."""
import argparse
import json
import os
import platform
import re
import sys


def command(flake, app, system, arguments):
    if not flake or flake.startswith('-') or '#' in flake or any(c in flake for c in ('\n','\r','\x00')):
        raise ValueError('Expected a project flake reference without an output fragment')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',app):raise ValueError('Invalid project app')
    if system not in ('aarch64-linux','x86_64-linux'):raise ValueError('Unsupported project system')
    values=json.loads(arguments)
    if not isinstance(values,list) or not all(isinstance(value,str) and '\x00' not in value for value in values):
        raise ValueError('PROJECT_ARGS_JSON must be a JSON array of strings')
    return ['nix','run','--no-write-lock-file',flake+'#apps.'+system+'.'+app,'--',*values]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--flake',required=True)
    parser.add_argument('--app',required=True)
    parser.add_argument('--system',required=True)
    parser.add_argument('--args-json',default='[]')
    args=parser.parse_args()
    if platform.system()!='Linux':raise ValueError('Project orchestration must run inside Nix-Alpine')
    argv=command(args.flake,args.app,args.system,args.args_json)
    print('PROJECT_EXECUTOR=linux app='+args.app+' system='+args.system,flush=True)
    os.execvp(argv[0],argv)


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:print('Project launch error: '+str(error),file=sys.stderr);sys.exit(2)
