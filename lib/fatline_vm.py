#!/usr/bin/env python3
"""Start only the selected Fatline VM through the existing runner adapter."""
import json
import os
from pathlib import Path
import subprocess
import sys
from compose_runtime import Runtime, REPO, run
from compositions import require
from agni_coreos_plan import resolve


def start():
    runtime = Runtime(os.environ)
    profile = os.environ.get('NIX_XD_FATLINE_PROFILE', 'vm1')
    require(profile in ('vm1', 'vm2'), 'Select vm1 or vm2')
    revision = runtime.owner('cat', runtime.flake + '/.nix-xd-source-revision')
    require(revision == os.environ['NIX_XD_WORKLOAD_REV'], 'Stage the selected revision first')
    plan, _ = resolve(runtime, profile)
    runtime.plan = {'placements':{profile:plan['placement']}, 'workloads':{'transport':{'placement':profile}}}
    env = runtime.environment('transport')
    run(['bash', str(REPO / 'bin/nix-xd-coreos-podman'), 'start'], env)
    run(['bash', str(REPO / 'bin/nix-xd-wisp-ssh')], env)
    print('FATLINE_VM_READY=' + profile, flush=True)


if __name__ == '__main__':
    try: start()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Fatline VM error: ' + str(error), file=sys.stderr)
        sys.exit(1)
