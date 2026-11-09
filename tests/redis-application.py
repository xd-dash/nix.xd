#!/usr/bin/env python3
"""Check direct exec arguments, request batching, and cleanup on failures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
MOCK = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log: log.write(json.dumps(args) + '\\n')
if args[0] == 'info': print('true')
elif args[0] == 'inspect': print('true' if 'State.Running' in args[-1] else 'container-id')
elif args[0] == 'exec':
    assert args[1] == 'nix-xd-test'
    command = args[2:]
    assert command[0] != '/bin/sh', 'application was shell-wrapped'
    if command[0].endswith('/redis-server'):
        assert command[command.index('--port') + 1] == '0'
        assert command[command.index('--appendonly') + 1] == 'no'
    elif command[0].endswith('/redis-benchmark'):
        assert command[command.index('-n') + 1] == '100'
        assert command[command.index('-t') + 1] == 'ping_mbulk'
        if os.environ.get('FAIL_BENCHMARK'): sys.exit(42)
        print('"PING_INLINE","10000.00"')
    elif command[-1] == 'PING': print('PONG')
else: sys.exit(1)
'''


class Application(unittest.TestCase):
    def test_requests_are_batched_and_server_is_stopped_even_on_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name, source in {'podman': MOCK, 'cat': '#!/bin/sh\necho test-boot\n',
                                     'timeout': '#!/bin/sh\nshift 3\nexec "$@"\n'}.items():
                    path = root / name
                    path.write_text(source)
                    path.chmod(0o755)
                env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], CALLS=str(root / 'calls'))
                if fail:
                    env['FAIL_BENCHMARK'] = '1'
                header = "unit=nix-xd-test\nexpected_boot=test-boot\napp=/nix/store/test-redis\nrequests=100\ndirectory=/run/nixuser/app-test\n"
                result = subprocess.run(['bash', '-se'], input=header + (REPO / 'qualifiers/redis-application.sh').read_text(),
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 42 if fail else 0, result.stderr)
                calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                self.assertEqual(sum('/nix/store/test-redis/bin/redis-benchmark' in args for args in calls), 1)
                self.assertTrue(any(args[-2:] == ['SHUTDOWN', 'NOSAVE'] for args in calls))
                self.assertIn('APPLICATION_CLEANUP=passed', result.stdout)
                if not fail:
                    self.assertIn('APPLICATION_RESULT=passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
