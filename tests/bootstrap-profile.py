#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootstrapProfile(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.record = self.directory / "calls"
        mock = self.directory / "podman"
        mock.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$PROFILE_TEST_RECORD"
if [[ ${PROFILE_TEST_COMPARISON:-0} == 1 ]]; then
  if [[ $1 == info ]]; then echo true; exit; fi
  case "$*" in
    *'{{.ProcessLabel}}'*) echo 'system_u:system_r:container_t:s0:c1,c2'; exit ;;
    *'{{.Id}}'*) echo fixture-id; exit ;;
    *'{{.Image}}'*) echo fixture-image; exit ;;
    *'.Mounts'*) echo owner-store; exit ;;
  esac
  if [[ $1 == run ]]; then
    if [[ $* == *'label=disable '* ]]; then exit "${PROFILE_TEST_DISABLED_STATUS:-0}"; fi
    echo 'unshare: mount /proc failed: Permission denied' >&2
    exit "${PROFILE_TEST_BASELINE_STATUS:-1}"
  fi
fi
if [[ $* == *".State.Running"* ]]; then echo "${PROFILE_TEST_RUNNING:-true}"; exit; fi
if [[ $* == *".Mounts"* ]]; then
  printf 'owner-store /nix true\\naux-store /stores/aux %s\\npeer-store /peer/peer false\\n' "${PROFILE_TEST_WRITABLE:-true}"
  exit
fi
if [[ $1 == exec ]]; then
  [[ $* != *"bash -se"* ]] || cat > "$PROFILE_TEST_STDIN"
  exit "${PROFILE_TEST_EXEC_STATUS:-0}"
fi
exit 99
''')
        mock.chmod(0o755)
        uname = self.directory / "uname"
        uname.write_text('#!/usr/bin/env bash\necho Linux\n')
        uname.chmod(0o755)
        self.environment = dict(os.environ, PATH=str(self.directory) + ':' + os.environ['PATH'],
                                NIX_XD_PROVIDER="podman", NIX_XD_SCOPE="owner",
                                NIX_XD_STORE_VOLUME="owner-store", NIX_XD_SYSTEM="aarch64-linux",
                                NIX_XD_BUILDER_RUNTIME_FLAKE="/workspaces/nix.xd20261111",
                                NIX_XD_PEER_STORES="peer=peer-store", BUILDER_CHROOT_STORES="aux=aux-store",
                                PROFILE_TEST_RECORD=str(self.record),
                                PROFILE_TEST_STDIN=str(self.directory / 'stdin'))

    def run_profile(self, action="ready", **environment):
        return subprocess.run(['bash', str(ROOT / 'bin/nix-xd-bootstrap-profile'), action],
                              cwd=ROOT, env=dict(self.environment, **environment),
                              text=True, capture_output=True)

    def test_ready_checks_declared_mounts_and_runs_capability_script(self):
        result = self.run_profile()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BOOTSTRAP_PROFILE_RESULT=ready scope=owner stores=2', result.stdout)
        self.assertIn('exec -i owner bash -se -- /workspaces/nix.xd20261111 /stores/aux',
                      self.record.read_text())
        self.assertEqual((self.directory / 'stdin').read_text(),
                         (ROOT / 'runtime/bootstrap-ready.sh').read_text())

    def test_bad_mount_stopped_builder_and_failed_capability_block_readiness(self):
        for setting in ({'PROFILE_TEST_WRITABLE': 'false'},
                        {'PROFILE_TEST_RUNNING': 'false'},
                        {'PROFILE_TEST_EXEC_STATUS': '7'}):
            with self.subTest(setting=setting):
                result = self.run_profile(**setting)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('BOOTSTRAP_PROFILE_RESULT=ready', result.stdout)

    def test_invalid_declaration_fails_before_runtime_operations(self):
        result = self.run_profile(BUILDER_CHROOT_STORES='aux=owner-store')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())

    def test_qualification_uses_each_selected_store_and_propagates_failure(self):
        result = self.run_profile('qualify')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--root /stores/aux', self.record.read_text())
        self.assertIn('#apps.aarch64-linux.chroot-store-poc', self.record.read_text())
        result = self.run_profile('qualify', PROFILE_TEST_EXEC_STATUS='7')
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('BOOTSTRAP_PROFILE_QUALIFICATION=passed', result.stdout)

    def test_default_bootstrap_has_no_post_start_retrofit(self):
        result = subprocess.run(['make', '--no-print-directory', '-sn', 'bootstrap-builder-profile',
                                 'ARCH=arm64', 'OS=Darwin', 'PROVIDER=podman', 'CHROOT_SELINUX=keep',
                                 'BUILDER_CHROOT_STORES=aux=aux-store'], cwd=ROOT,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NIX_XD_INITIAL_PROFILE='1'", result.stdout)
        self.assertIn("NIX_XD_INITIAL_CHROOT_STORES='aux=aux-store'", result.stdout)
        self.assertNotIn('bin/nix-xd-chroot-attach', result.stdout)
        self.assertNotIn('bin/nix-xd-builder-profile apply', result.stdout)

    def test_store_owner_allows_readers_but_rejects_another_writer(self):
        script = '''source lib/builder-stores.sh
fake() {
  if [[ $1 == ps ]]; then echo fixture; return; fi
  if [[ $* == *'{{.Name}}'* ]]; then echo "$TEST_OWNER"; return; fi
  echo "$TEST_MOUNT"
}
builder_store_assert_owner owner store /nix fake
'''
        for owner, mount, success in [('reader', '/peer/source false', True),
                                      ('writer', '/nix true', False),
                                      ('owner', '/nix true', True),
                                      ('owner', '/wrong true', False)]:
            with self.subTest(owner=owner, mount=mount):
                result = subprocess.run(['bash', '-eu', '-c', script], cwd=ROOT,
                                        env=dict(os.environ, TEST_OWNER=owner, TEST_MOUNT=mount),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def run_comparison(self, **environment):
        policy = self.directory / '.config/nix-xd/seccomp/owner-nix-chroot.json'
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text('{}')
        return subprocess.run(['bash', str(ROOT / 'runtime/bootstrap-profile-compare.sh'),
                               'owner', 'owner-store'], cwd=ROOT,
                              env=dict(self.environment, HOME=str(self.directory),
                                       PROFILE_TEST_COMPARISON='1', **environment),
                              text=True, capture_output=True)

    def test_comparison_uses_read_only_probes_and_leaves_owner_unchanged(self):
        result = self.run_comparison()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BOOTSTRAP_PROFILE_COMPARISON_RESULT=isolated-selinux', result.stdout)
        calls = self.record.read_text().splitlines()
        probes = [line for line in calls if line.startswith('run ')]
        self.assertEqual(len(probes), 2)
        for probe in probes:
            self.assertIn('--mount type=volume,src=owner-store,dst=/nix,ro', probe)
            self.assertIn('--read-only --user 1000:1000', probe)
            self.assertIn('--security-opt seccomp=', probe)
        self.assertIn('label=type:container_t', probes[0])
        self.assertIn('label=disable', probes[1])
        self.assertFalse(any('restart' in line or 'volume create' in line for line in calls))

    def test_comparison_does_not_claim_isolation_when_results_do_not_differ(self):
        for setting in ({'PROFILE_TEST_DISABLED_STATUS': '1'},
                        {'PROFILE_TEST_BASELINE_STATUS': '0'}):
            with self.subTest(setting=setting):
                result = self.run_comparison(**setting)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('BOOTSTRAP_PROFILE_COMPARISON_RESULT=not-isolated', result.stdout)


if __name__ == '__main__':
    unittest.main()
