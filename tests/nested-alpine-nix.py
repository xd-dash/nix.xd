#!/usr/bin/env python3
"""Build the real workload and exercise its read-only store in a CI chroot."""
import importlib.util
import os
import pwd
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
        for directory, options in [('tmp', 'mode=1777'), ('run', 'mode=1777'),
                                   ('nix/var', 'mode=1777'),
                                   ('home', 'mode=1777')]:
            mount(scratch / directory, '-t', 'tmpfs', '-o', 'nosuid,nodev,' + options, 'tmpfs')
        env = dict(os.environ, HOME='/home/nixuser', USER='nixuser', LOGNAME='nixuser',
                   PATH='/usr/local/bin:/usr/bin:/bin', NIX_REMOTE='local', XDG_RUNTIME_DIR='/run/nixuser')
        env.pop('NIX_CONFIG', None)
        subprocess.run(['/usr/sbin/chroot', '--userspec=1000:1000', str(scratch), '/usr/local/bin/nix-alpine-init', manifest['executable']],
                       env=env, check=True)
        print('PASS: real Alpine base, UID 1000, shared read-only store, guest-local metadata, Nix and dynamic executable')
        # Exercise the production executor and Podman options, substituting a
        # local read-only bind for the unavailable QEMU 9P transport on CI.
        uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
        assert uid != 0
        runner = pwd.getpwuid(uid).pw_name
        tools = scratch.parent / (scratch.name + '-tools')
        tools.mkdir(mode=0o755)
        (tools / 'podman').write_text('#!/bin/sh\nexec /usr/bin/podman --cgroup-manager=cgroupfs --events-backend=file --storage-driver=vfs "$@"\n')
        (tools / 'findmnt').write_text('#!/bin/sh\nif [ "$*" = "-rn -o FSTYPE --mountpoint /var/mnt/nixstore" ]; then echo 9p; else exec /usr/bin/findmnt "$@"; fi\n')
        for tool in ('podman', 'findmnt'):
            (tools / tool).chmod(0o755)
        home = tools / 'home'
        runtime = tools / 'runtime'
        for directory in (home, runtime):
            directory.mkdir(mode=0o700)
            os.chown(directory, uid, gid)
        share = Path('/var/mnt/nixstore')
        assert not share.exists()
        share.mkdir(parents=True)
        mount(share, '--bind', '/nix/store')
        subprocess.run(['mount', '-o', 'remount,bind,ro', str(share)], check=True)
        subprocess.run(['setpriv', '--reuid=' + str(uid), '--regid=' + str(gid), '--init-groups',
                        '/usr/bin/env', '-i', 'HOME=' + str(home), 'USER=' + runner, 'LOGNAME=' + runner,
                        'XDG_RUNTIME_DIR=' + str(runtime), 'PATH=' + str(tools) + ':/usr/bin:/bin',
                        'NIX_XD_WORKLOAD_CONTAINER=nix-xd-ci-alpine', '/bin/bash',
                        str(repo / 'bin/nix-xd-guest-store-exec'), '--rootfs-archive',
                        manifest['rootfsArchive'], manifest['executable']], check=True)
        print('PASS: production executor with real rootless Podman, keep-id UID 1000 and guest-local tmpfs')

finally:
    unmounted = True
    for path in reversed(mounts):
        if subprocess.run(['umount', str(path)]).returncode:
            unmounted = False
    if unmounted:
        shutil.rmtree(scratch)
    # Rootless Podman storage may contain subordinate-owned files. The runner
    # is disposable; leave that private tool directory to runner cleanup.
    shutil.rmtree(source)
    shutil.rmtree(roots, ignore_errors=True)
