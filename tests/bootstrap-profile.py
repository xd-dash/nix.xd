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
if [[ $1 == machine && $2 == ssh ]]; then
  cat > "$PROFILE_TEST_STDIN"
  exit "${PROFILE_TEST_SSH_STATUS:-0}"
fi
if [[ ${PROFILE_TEST_COMPARISON:-0} == 1 ]]; then
  if [[ $1 == info ]]; then echo true; exit; fi
  if [[ $1 == container && $2 == exists ]]; then exit 0; fi
  if [[ $1 == rm ]]; then exit 0; fi
  case "$*" in
    *'{{.ProcessLabel}}'*) echo 'system_u:system_r:container_t:s0:c1,c2'; exit ;;
    *'{{.Id}}'*) echo fixture-id; exit ;;
    *'{{.Image}}'*) echo fixture-image; exit ;;
    *'{{.Mountpoint}}'*) echo /fixture/volume; exit ;;
    *'.Mounts'*) echo owner-store; exit ;;
  esac
  if [[ $1 == run ]]; then
    if [[ $* == *'label=type:container_userns_t '* ]]; then exit "${PROFILE_TEST_USERNS_STATUS:-0}"; fi
    if [[ $* == *'label=disable '* ]]; then exit "${PROFILE_TEST_DISABLED_STATUS:-0}"; fi
    echo 'unshare: mount /proc failed: Permission denied' >&2
    exit "${PROFILE_TEST_BASELINE_STATUS:-1}"
  fi
fi
if [[ $* == *".State.Running"* ]]; then echo "${PROFILE_TEST_RUNNING:-true}"; exit; fi
if [[ $* == *".ProcessLabel"* ]]; then echo "${PROFILE_TEST_LABEL:-}"; exit; fi
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
        getenforce = self.directory / 'getenforce'
        getenforce.write_text('#!/usr/bin/env bash\necho "${PROFILE_TEST_ENFORCEMENT:-Enforcing}"\n')
        getenforce.chmod(0o755)
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

    def test_disabled_label_is_explicit_in_initial_quadlet_and_readiness(self):
        script = '''source lib/builder-stores.sh
builder_stores_init owner
NIX_XD_INITIAL_CHROOT_STORES=aux=aux-store
NIX_XD_INITIAL_SECCOMP_PATH="$HOME/.config/nix-xd/seccomp/owner-nix-chroot.json"
builder_quadlet owner localhost/nix-xd:arm64 Fixture
'''
        for policy in ('keep', 'userns', 'disabled'):
            result = subprocess.run(['bash', '-eu', '-c', script], cwd=ROOT,
                                    env=dict(self.environment, NIX_XD_CHROOT_SELINUX=policy),
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual('SecurityLabelDisable=true' in result.stdout, policy == 'disabled')
            self.assertEqual('SecurityLabelType=container_userns_t' in result.stdout, policy == 'userns')
            self.assertIn('SeccompProfile=', result.stdout)
            self.assertNotIn('Privileged=true', result.stdout)
        result = self.run_profile(NIX_XD_CHROOT_SELINUX='disabled', PROFILE_TEST_LABEL='container_t')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('BOOTSTRAP_PROFILE_RESULT=ready', result.stdout)

    def test_userns_readiness_requires_expected_type_and_enforcement(self):
        label = 'system_u:system_r:container_userns_t:s0:c1,c2'
        result = self.run_profile(NIX_XD_CHROOT_SELINUX='userns', PROFILE_TEST_LABEL=label)
        self.assertEqual(result.returncode, 0, result.stderr)
        for values in ({'PROFILE_TEST_LABEL': 'system_u:system_r:container_t:s0:c1,c2'},
                       {'PROFILE_TEST_LABEL': label, 'PROFILE_TEST_ENFORCEMENT': 'Permissive'}):
            result = self.run_profile(NIX_XD_CHROOT_SELINUX='userns', **values)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('BOOTSTRAP_PROFILE_RESULT=ready', result.stdout)

    def test_userns_policy_check_is_read_only_and_has_no_disabled_fallback(self):
        policy = self.directory / '.config/nix-xd/seccomp/owner-nix-chroot.json'
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text('{}')
        stat = self.directory / 'stat'
        stat.write_text('#!/usr/bin/env bash\necho system_u:object_r:container_file_t:s0\n')
        stat.chmod(0o755)
        env = dict(self.environment, HOME=str(self.directory), PROFILE_TEST_COMPARISON='1')
        result = subprocess.run(['bash', str(ROOT / 'runtime/bootstrap-profile-userns.sh'),
                                 'owner', 'owner-store'], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.record.read_text()
        self.assertIn('--security-opt label=type:container_userns_t', calls)
        self.assertIn('type=volume,src=owner-store,dst=/nix,ro', calls)
        self.assertNotIn('label=disable', calls)
        self.assertNotIn('setsebool', calls)
        self.assertNotIn('systemctl', calls)
        result = subprocess.run(['bash', str(ROOT / 'runtime/bootstrap-profile-userns.sh'),
                                 'owner', 'owner-store'],
                                env=dict(env, PROFILE_TEST_USERNS_STATUS='7'),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('BOOTSTRAP_USERNS_POLICY_CHECK=passed', result.stdout)
        self.record.unlink()
        result = subprocess.run(['bash', str(ROOT / 'runtime/bootstrap-profile-userns.sh'),
                                 'owner', 'owner-store'],
                                env=dict(env, PROFILE_TEST_ENFORCEMENT='Permissive'),
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())

    def test_failed_userns_policy_check_prevents_builder_recreation(self):
        uname = self.directory / 'uname'
        uname.write_text('#!/usr/bin/env bash\necho Darwin\n')
        result = self.run_profile('recreate', NIX_XD_CHROOT_SELINUX='userns',
                                  NIX_XD_MACHINE='fixture', PROFILE_TEST_SSH_STATUS='7')
        self.assertEqual(result.returncode, 7)
        calls = self.record.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertEqual((self.directory / 'stdin').read_text(),
                         (ROOT / 'runtime/bootstrap-profile-userns.sh').read_text())

    def test_userns_profile_accepts_multiple_independent_store_slots(self):
        env = dict(self.environment, NIX_XD_CHROOT_SELINUX='userns',
                   BUILDER_CHROOT_STORES='aux=aux-store scratch=scratch-store')
        result = subprocess.run(['bash', str(ROOT / 'bin/nix-xd-builder-store-profile'), 'plan'],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('selinux=userns', result.stdout)
        self.assertIn('path=/stores/aux rw=true', result.stdout)
        self.assertIn('path=/stores/scratch rw=true', result.stdout)
        result = subprocess.run(['bash', str(ROOT / 'bin/nix-xd-builder-store-profile'), 'apply'],
                                env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not post-start apply', result.stderr)
        self.assertFalse(self.record.exists())

    def test_recreation_retains_stores_and_removes_only_managed_builder(self):
        unit = self.directory / '.config/containers/systemd/owner.container'
        unit.parent.mkdir(parents=True)
        unit.write_text('ContainerName=owner\nLabel=io.nix-xd.managed=true\nLabel=io.nix-xd.role=builder\n')
        mock = self.directory / 'systemctl'
        mock.write_text('#!/usr/bin/env bash\nprintf "systemctl %s\\n" "$*" >> "$PROFILE_TEST_RECORD"\n')
        mock.chmod(0o755)
        result = subprocess.run(['bash', str(ROOT / 'runtime/bootstrap-profile-recreate.sh'), 'owner'],
                                env=dict(self.environment, HOME=str(self.directory),
                                         PROFILE_TEST_COMPARISON='1', PROFILE_TEST_RUNNING='false'),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(unit.exists())
        calls = self.record.read_text()
        self.assertIn('systemctl --user stop owner.service', calls)
        self.assertIn('rm owner', calls)
        self.assertNotIn('volume rm', calls)
        self.assertNotIn('image rm', calls)
        self.assertNotIn('volume create', calls)


if __name__ == '__main__':
    unittest.main()
