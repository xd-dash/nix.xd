#!/usr/bin/env python3
"""Export a pinned Nix owner artifact to the host with a verified digest."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

from compositions import require

STORE = re.compile(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+')
SHA = re.compile(r'[a-f0-9]{64}')


def export_executable(runtime, flake, app, destination, expected_target):
    require(flake and (flake.startswith('/workspaces/') or flake.startswith('github:')),
            'Select a staged or immutable composition artifact flake')
    require(re.fullmatch(r'[a-z0-9][a-z0-9-]*', app), 'Invalid artifact app')
    output = runtime.owner('nix', 'run', '--no-write-lock-file', '--no-update-lock-file',
                           flake + '#' + app)
    fields = dict(line.split('=', 1) for line in output.splitlines()
                  if line.startswith('ARTIFACT_') and line.count('=') == 1)
    path = fields.get('ARTIFACT_STORE_PATH', '')
    digest = fields.get('ARTIFACT_SHA256', '')
    revision = fields.get('ARTIFACT_SOURCE_REV', '')
    require(STORE.fullmatch(path) and SHA.fullmatch(digest) and
            re.fullmatch(r'[a-f0-9]{40}', revision) and
            fields.get('ARTIFACT_TARGET') == expected_target,
            'Composition artifact output has invalid identity')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.artifact-', delete=False) as temp:
        candidate = Path(temp.name)
    try:
        subprocess.run([*runtime.podman, 'cp', runtime.scope + ':' + path, str(candidate)],
                       check=True, env=runtime.env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        require(hashlib.sha256(candidate.read_bytes()).hexdigest() == digest,
                'Exported artifact digest differs from Nix owner')
        candidate.chmod(0o700)
        os.replace(candidate, destination)
    finally:
        candidate.unlink(missing_ok=True)
    return {'path': str(destination), 'storePath': path, 'sha256': digest,
            'sourceRevision': revision, 'target': expected_target, 'flake': flake}
