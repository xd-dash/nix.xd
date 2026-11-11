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
from nix_alpine_runtime.builder_policy import render as render_policy
from nix_alpine_runtime.store_poc import policy_diagnostics, view_command
from nix_alpine_runtime.launch import command, selected_store, store_options


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

    def test_chroot_requires_sandbox_without_changing_normal_store_policy(self):
        self.assertEqual(store_options('local'),['--store','local'])
        options=store_options('/stores/grumble')
        self.assertEqual(options,['--store','/stores/grumble','--option','sandbox','true','--option','sandbox-fallback','false'])
        self.assertIn('sandbox',command('/project','check','aarch64-linux','[]','/stores/grumble'))

    def test_store_selection_is_explicit_and_scoped(self):
        argv=command('/project','check','aarch64-linux','[]','/stores/grumble')
        self.assertEqual(argv[argv.index('--store')+1],'/stores/grumble')
        for bad in ('/','/nix','/stores/grumble/../other','daemon','local?root=/tmp/other'):
            with self.assertRaises(ValueError):selected_store(bad)

    def test_oci_diagnostic_prints_only_selected_security_fields(self):
        spec={'process':{'env':['CREDENTIAL=private-fixture-value'],'args':['secret-command'],'apparmorProfile':'fixture'},
            'linux':{'seccomp':{'defaultAction':'SCMP_ACT_ERRNO','syscalls':[{'names':['mount','read'],'action':'SCMP_ACT_ALLOW'}]}}}
        output=io.StringIO()
        with contextlib.redirect_stdout(output):policy_diagnostics(spec)
        data=json.loads(output.getvalue())['ociPolicy']
        self.assertEqual(data['namespaceSyscallRules'][0]['names'],['mount'])
        self.assertNotIn('private-fixture-value',output.getvalue())
        self.assertNotIn('secret-command',output.getvalue())

    def test_builder_policy_changes_only_uts_syscalls_and_is_idempotent(self):
        policy={'defaultAction':'SCMP_ACT_ERRNO','architectures':['SCMP_ARCH_AARCH64'],
            'syscalls':[{'names':['sethostname','setns'],'action':'SCMP_ACT_ERRNO','errnoRet':1},
                {'names':['mount','read'],'action':'SCMP_ACT_ALLOW'}]}
        original=json.loads(json.dumps(policy))
        result=render_policy({'linux':{'seccomp':policy}})
        self.assertEqual(policy,original)
        self.assertEqual(result['defaultAction'],original['defaultAction'])
        self.assertEqual(result['architectures'],original['architectures'])
        self.assertEqual(result['syscalls'][0],{'names':['setns'],'action':'SCMP_ACT_ERRNO','errnoRet':1})
        self.assertEqual(result['syscalls'][1],original['syscalls'][1])
        self.assertEqual(result['syscalls'][2],{'names':['setdomainname','sethostname'],'action':'SCMP_ACT_ALLOW'})
        self.assertEqual(render_policy({'linux':{'seccomp':result}}),result)
        for invalid in ({},{'linux':{'seccomp':{'defaultAction':'SCMP_ACT_ALLOW'}}}):
            with self.assertRaises(ValueError):render_policy(invalid)

    def test_store_view_runs_a_named_app_in_the_selected_store(self):
        argv=view_command('/stores/grumble','/workspaces/project','aarch64-linux','/nix/store/own','/nix/store/foreign')
        self.assertIn('/workspaces/project#apps.aarch64-linux.store-poc-view',argv)
        self.assertEqual(argv[argv.index('--store')+1],'/stores/grumble')
        self.assertEqual(argv[argv.index('--')+1:],['view','--path','/nix/store/own','--foreign','/nix/store/foreign'])

    def test_invalid_arguments_are_rejected(self):
        for arguments in ('{}','[1]','[null]'):
            with self.assertRaises(ValueError):command('/project','startup','aarch64-linux',arguments)
        with self.assertRaises(ValueError):command('/project#unexpected','startup','aarch64-linux','[]')


if __name__=='__main__':unittest.main()
