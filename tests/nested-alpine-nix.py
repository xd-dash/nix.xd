#!/usr/bin/env python3
"""Build the real workload and exercise its read-only store in a CI chroot."""
import importlib.util
import os
import pwd
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

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
        run_as_user = ['setpriv', '--reuid=' + str(uid), '--regid=' + str(gid), '--init-groups',
                       '/usr/bin/env', '-i', 'HOME=' + str(home), 'USER=' + runner, 'LOGNAME=' + runner,
                       'XDG_RUNTIME_DIR=' + str(runtime), 'PATH=' + str(tools) + ':/usr/bin:/bin']
        executor = ['/bin/bash', str(repo / 'bin/nix-xd-guest-store-exec'), '--rootfs-archive']
        subprocess.run([*run_as_user, 'NIX_XD_WORKLOAD_CONTAINER=nix-xd-ci-alpine',
                        *executor, manifest['rootfsArchive'], manifest['executable']], check=True)
        print('PASS: production executor with real rootless Podman, keep-id UID 1000 and guest-local tmpfs')

        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        with c.locked('nix-alpine-env'):
            service = c.prepare('nix-alpine-env', 'x86_64-linux', str(source), revision)
            generation = service['generation']
            c.lifecycle('begin-activate', 'nix-alpine-env', target=boot_id)
            c.lifecycle('confirm-active', 'nix-alpine-env', generation)
        service_manifest = service['manifest']
        rootless_podman = [*run_as_user, str(tools / 'podman')]
        service_name = 'nix-xd-nix-alpine-env-' + generation[:32]
        logs = []

        def launch(container):
            log = (tools / (container + '.log')).open('w+')
            logs.append(log)
            return subprocess.Popen([*run_as_user, 'NIX_XD_WORKLOAD_CONTAINER=' + container,
                                     *executor, service_manifest['rootfsArchive'], service_manifest['executable']],
                                    stdout=log, stderr=subprocess.STDOUT), log

        def wait_ready(process, log, container):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                probe = subprocess.run([*rootless_podman, 'exec', container,
                                        service_manifest['readinessExecutable']], capture_output=True, text=True)
                if probe.returncode == 0:
                    assert 'NIX_ALPINE_READY=passed' in probe.stdout
                    return
                time.sleep(1)
            raise AssertionError('Managed environment did not become ready')

        def stop_instance(process, container):
            stopped = subprocess.run([*rootless_podman, 'stop', '--time', '10', container],
                                     check=True, capture_output=True, text=True)
            assert 'resorting to SIGKILL' not in stopped.stderr, stopped.stderr
            assert process.wait(timeout=60) == 0
            assert subprocess.run([*rootless_podman, 'container', 'exists', container]).returncode == 1

        def snapshot(stage, container, transaction, instance):
            cid = subprocess.check_output([*rootless_podman, 'inspect', container, '--format', '{{.Id}}'], text=True).strip()
            evidence = subprocess.check_output([*rootless_podman, 'exec', '-i', container, '/bin/sh', '-s'],
                input=c.container_recreation_probe(stage, transaction), text=True)
            identities = {'BOOT_ID': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'GENERATION': generation, 'TRANSACTION': transaction, 'INSTANCE': instance or 'legacy', 'CONTAINER_ID': cid}
            return evidence + ''.join('RECREATE_' + key + '=' + value + '\n' for key, value in identities.items())

        process, log = launch(service_name)
        try:
            wait_ready(process, log, service_name)
            assert c.lifecycle('summary', 'nix-alpine-env')['rootsRetained']
            shell = subprocess.check_output([*rootless_podman, 'exec', '-i', '--user', '1000:1000',
                    service_name, '/bin/sh', '-ec',
                    'test "$(id -u)" = 1000; nix --version; test -f "$XDG_RUNTIME_DIR/ready"; echo SHELL_OK'], text=True)
            assert 'SHELL_OK' in shell
            transaction = c.recreation('begin-recreate', 'nix-alpine-env', generation, target=boot_id)
            before = snapshot('before', service_name, transaction, None)
            c.recreation('recreate-record-before', 'nix-alpine-env', generation, transaction=transaction, evidence=before)
            fingerprint = c.assert_retained(c.load('nix-alpine-env'), 'nix-alpine-env', generation)
            stop_instance(process, service_name)
            assert fingerprint == c.assert_retained(c.load('nix-alpine-env'), 'nix-alpine-env', generation)
            c.recreation('recreate-stopped', 'nix-alpine-env', generation, transaction=transaction)
            instance = c.load('nix-alpine-env')['generations'][generation]['instance']
            service_name = 'nix-xd-nix-alpine-env-' + generation[:16] + '-' + instance[:16]
            process, log = launch(service_name)
            c.recreation('recreate-activated', 'nix-alpine-env', generation, transaction=transaction)
            wait_ready(process, log, service_name)
            c.recreation('recreate-checked', 'nix-alpine-env', generation, transaction=transaction)
            after = snapshot('after', service_name, transaction, instance)
            c.recreation('recreate-record-after', 'nix-alpine-env', generation, transaction=transaction, evidence=after)
            c.recreation('confirm-recreated', 'nix-alpine-env', generation, transaction=transaction)
            assert fingerprint == c.assert_retained(c.load('nix-alpine-env'), 'nix-alpine-env', generation)
            print('PASS: new container ID, same boot/generation/store paths, fresh writable state and continuously retained roots')
        finally:
            entry = c.load('nix-alpine-env')['generations'][generation]
            if entry['status'].startswith('recreating-'):
                c.recreation('abandon-recreate', 'nix-alpine-env', generation, transaction=entry['recreation']['id'])
            c.lifecycle('begin-stop', 'nix-alpine-env', target=boot_id)
            if process.poll() is None:
                stop_instance(process, service_name)
            assert subprocess.run([*rootless_podman, 'container', 'exists', service_name]).returncode == 1
            c.lifecycle('confirm-stopped', 'nix-alpine-env', generation)
            for log in logs:
                log.close()
        assert not c.lifecycle('summary', 'nix-alpine-env')['rootsRetained']
        print('PASS: managed service remains running, readiness and shell exec work, roots release after stop')


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
