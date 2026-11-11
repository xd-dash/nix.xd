#!/usr/bin/env python3
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from nix_alpine_runtime import run,scoped_lock,write_json
from nix_alpine_runtime.launch import command, selected_store


class RuntimePrimitives(unittest.TestCase):
    def test_failed_command_preserves_output_and_exit_status(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(subprocess.CalledProcessError) as result:
                run([sys.executable,'-c','print("evidence");raise SystemExit(7)'],os.environ,True)
        self.assertEqual(result.exception.returncode,7)
        self.assertIn('evidence',out.getvalue())

    def test_timeout_is_not_success(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run([sys.executable,'-c','import time;time.sleep(10)'],os.environ,True,timeout=0.05)

    def test_atomic_write_failure_preserves_previous_record_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'state.json';write_json(path,{'generation':'previous'})
            with patch('nix_alpine_runtime.os.replace',side_effect=OSError('fixture')):
                with self.assertRaises(OSError):write_json(path,{'generation':'next'})
            self.assertEqual(json.loads(path.read_text()),{'generation':'previous'})
            self.assertEqual(list(root.iterdir()),[path])

    def test_same_lock_excludes_and_independent_locks_proceed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with scoped_lock(root/'one.lock'):
                with self.assertRaises(BlockingIOError):
                    with scoped_lock(root/'one.lock'):self.fail('second writer entered')
                with scoped_lock(root/'two.lock'):pass
            with scoped_lock(root/'one.lock'):pass

    def test_project_arguments_remain_literal(self):
        args=['space value',"quote'value",'$(touch /tmp/unwanted)', '--flag']
        argv=command('/workspaces/project','startup','aarch64-linux',json.dumps(args))
        self.assertEqual(argv[-len(args):],args)
        self.assertIn('/workspaces/project#apps.aarch64-linux.startup',argv)

    def test_store_selection_is_explicit_and_scoped(self):
        argv=command('/project','check','aarch64-linux','[]','/stores/grumble')
        self.assertEqual(argv[argv.index('--store')+1],'/stores/grumble')
        for bad in ('/','/nix','/stores/grumble/../other','daemon','local?root=/tmp/other'):
            with self.assertRaises(ValueError):selected_store(bad)

    def test_invalid_arguments_are_rejected(self):
        for arguments in ('{}','[1]','[null]'):
            with self.assertRaises(ValueError):command('/project','startup','aarch64-linux',arguments)
        with self.assertRaises(ValueError):command('/project#unexpected','startup','aarch64-linux','[]')


if __name__=='__main__':unittest.main()
