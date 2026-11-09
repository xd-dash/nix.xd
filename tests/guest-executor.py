#!/usr/bin/env python3
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class StoreNamespace(unittest.TestCase):
    def test_absolute_store_symlink_is_deferred_to_container_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / 'shared'
            export.mkdir()
            archive_name = 'a' * 32 + '-alpine.tar.gz'
            command = '/nix/store/' + 'b' * 32 + '-joined/bin/program'
            target = '/nix/store/' + 'c' * 32 + '-script/bin/program'
            physical_command = export / command.removeprefix('/nix/store/')
            physical_target = export / target.removeprefix('/nix/store/')
            physical_command.parent.mkdir(parents=True)
            physical_target.parent.mkdir(parents=True)
            physical_target.write_text('#!/bin/sh\necho okay\n')
            physical_target.chmod(0o755)
            physical_command.symlink_to(target)
            self.assertFalse(os.access(physical_command, os.X_OK))
            with tarfile.open(export / archive_name, 'w:gz') as archive:
                for name in ('etc', 'bin', 'nix', 'nix/store'):
                    member = tarfile.TarInfo(name)
                    member.type = tarfile.DIRTYPE
                    member.mode = 0o755
                    archive.addfile(member)
                for name, data, mode in [('etc/alpine-release', b'3.23.0\n', 0o644),
                                         ('bin/busybox', b'fixture', 0o755)]:
                    member = tarfile.TarInfo(name)
                    member.mode = mode
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            tools = root / 'bin'
            tools.mkdir()
            (tools / 'id').write_text('#!/bin/sh\necho 1001\n')
            (tools / 'findmnt').write_text('#!/bin/sh\ncase "$*" in *FSTYPE*) echo 9p;; *OPTIONS*) echo ro;; esac\n')
            (tools / 'podman').write_text('''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1] == 'info': print('true')
else:
    assert sys.argv[1] == 'run'
    with open(os.environ['RECORD'], 'w') as f: json.dump(sys.argv[2:], f)
''')
            for path in tools.iterdir():
                path.chmod(0o755)
            helper = root / 'executor'
            # Relocate only the export mount for this filesystem fixture.
            helper.write_text((REPO / 'bin/nix-xd-guest-store-exec').read_text().replace(
                'mountpoint=/var/mnt/nixstore', 'mountpoint=' + str(export)))
            runtime = root / 'runtime'
            runtime.mkdir()
            env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'],
                       RECORD=str(root / 'calls'), XDG_RUNTIME_DIR=str(runtime))
            result = subprocess.run(['bash', str(helper), '--rootfs-archive',
                                     '/nix/store/' + archive_name, command], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = json.loads((root / 'calls').read_text())
            self.assertEqual(arguments[-1], command)
            self.assertIn('type=bind,src=/var/mnt/nixstore,dst=/nix/store,ro', arguments)


if __name__ == '__main__':
    unittest.main()
