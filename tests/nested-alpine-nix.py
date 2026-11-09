#!/usr/bin/env python3
"""Build the real workload and exercise its read-only store in a CI chroot."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

assert os.environ.get('GITHUB_ACTIONS') == 'true' and os.getuid() == 0
repo = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller', repo / 'lib/workloads.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
source = Path('/workspaces/nix-xd-ci-alpine')
assert not source.exists()
source.mkdir(parents=True)
archive = subprocess.check_output(['git', '-C', str(repo), 'archive', 'HEAD'])
subprocess.run(['tar', '--no-same-owner', '-xf', '-', '-C', str(source)], input=archive, check=True)
revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
(source / '.nix-xd-source-revision').write_text(revision + '\n')
os.environ['NIX_CONFIG'] = 'experimental-features = nix-command flakes\nbuild-users-group =\nsandbox = false\n'
roots = Path('/nix/var/nix/gcroots/nix-xd/nested-alpine-ci')
assert not roots.exists()
scratch = Path(tempfile.mkdtemp(prefix='nix-xd-alpine-ci-'))
mounts = []


def mount(path, *args):
    subprocess.run(['mount', *args, str(path)], check=True)
    mounts.append(path)


try:
    with tempfile.TemporaryDirectory() as state:
        c = m.Controller(state, roots, repo / 'bin/nix-xd-guest-store-exec')
        with c.locked('nix-alpine'):
            prepared = c.prepare('nix-alpine', 'x86_64-linux', str(source), revision)
        manifest = prepared['manifest']
        assert manifest['rootfsArchive'] and not manifest['shell']
        subprocess.run(['tar', '--extract', '--gzip', '--no-same-owner', '--file', manifest['rootfsArchive'],
                        '--directory', str(scratch)], check=True)
        assert (scratch / 'etc/alpine-release').read_text().strip() == '3.23.0'
        assert not list((scratch / 'nix/store').iterdir()), 'Rootfs embeds copied store content'
        mount(scratch, '--bind', str(scratch))
        subprocess.run(['mount', '-o', 'remount,bind,ro', str(scratch)], check=True)
        mount(scratch / 'proc', '-t', 'proc', 'proc')
        mount(scratch / 'dev', '--bind', '/dev')
        mount(scratch / 'nix/store', '--bind', '/nix/store')
        subprocess.run(['mount', '-o', 'remount,bind,ro', str(scratch / 'nix/store')], check=True)
        for directory, options in [('tmp', 'mode=1777'), ('run', 'mode=0755,uid=1000,gid=1000'),
                                   ('nix/var', 'mode=0755,uid=1000,gid=1000'),
                                   ('home/nixuser', 'mode=0700,uid=1000,gid=1000')]:
            mount(scratch / directory, '-t', 'tmpfs', '-o', 'nosuid,nodev,' + options, 'tmpfs')
        env = dict(os.environ, HOME='/home/nixuser', USER='nixuser', LOGNAME='nixuser',
                   PATH='/usr/local/bin:/usr/bin:/bin', NIX_REMOTE='local')
        env.pop('NIX_CONFIG', None)
        subprocess.run(['/usr/sbin/chroot', '--userspec=1000:1000', str(scratch), manifest['executable']],
                       env=env, check=True)
        print('PASS: real Alpine base, UID 1000, shared read-only store, guest-local metadata, Nix and dynamic executable')
finally:
    unmounted = True
    for path in reversed(mounts):
        if subprocess.run(['umount', str(path)]).returncode:
            unmounted = False
    if unmounted:
        shutil.rmtree(scratch)
    shutil.rmtree(source)
    shutil.rmtree(roots, ignore_errors=True)
