#!/usr/bin/env python3
"""Resolve and retain workloads in the single Nix store owner."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

NAME = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")
STORE = re.compile(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+\Z")
SYSTEMS = {"aarch64-linux", "x86_64-linux"}
CAPABILITIES = ["store-9p-ro", "user-systemd", "rootless-podman"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        tmp.write_text(canonical(value))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Controller:
    def __init__(self, state, roots, executor):
        self.state = Path(state)
        self.roots = Path(roots)
        self.executor = Path(executor)

    @contextlib.contextmanager
    def locked(self, name):
        require(NAME.fullmatch(name), "Invalid workload name")
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / (name + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def nix(self, *args):
        return subprocess.check_output(["nix", *args], text=True).strip()

    def path(self, name):
        return self.state / (name + ".json")

    def load(self, name):
        path = self.path(name)
        return json.loads(path.read_text()) if path.exists() else {
            "version": 1, "name": name, "prepared": None, "active": None, "generations": {}}

    def prepare(self, name, system, flake, revision):
        require(system in SYSTEMS, "Unsupported system")
        require(re.fullmatch(r"[0-9a-f]{40}", revision), "Expected a pinned Git revision")
        require(re.fullmatch(r"/workspaces/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", flake)
                and ".." not in flake, "Expected a staged workspace flake")
        staged = Path(flake) / ".nix-xd-source-revision"
        require(staged.read_text().strip() == revision, "Staged source revision differs; restage the pinned checkout")
        metadata = json.loads(self.nix("flake", "metadata", "--json", "--no-write-lock-file", flake))
        source = metadata["path"]
        require(STORE.fullmatch(source), "Flake source is not an immutable store path")
        require((Path(source) / ".nix-xd-source-revision").read_text().strip() == revision,
                "Immutable flake source revision mismatch")
        nar_hash = metadata["locked"]["narHash"]
        require(nar_hash.startswith("sha256-"), "Missing source NAR hash")
        declaration = json.loads(self.nix("eval", "--json", "--no-write-lock-file",
                                          source + "#workloads." + system + "." + name))
        self.validate(declaration, name, system)
        root_parent = self.roots / name
        require(not self.roots.is_symlink() and not root_parent.is_symlink(), "Root namespace is a symlink")
        root_parent.mkdir(parents=True, exist_ok=True)
        pending = root_parent / (".pending-" + uuid.uuid4().hex)
        pending.mkdir()
        try:
            subprocess.run(["nix-store", "--realise", "--add-root", str(pending / "source"), source], check=True, stdout=subprocess.DEVNULL)
            outputs = {"source": {"path": source, "closure": [source]}}
            # Build with permanent out-links so there is no unrooted build/register gap.
            for label, output in sorted(declaration["outputs"].items()):
                path = self.nix("build", "--no-write-lock-file", "--print-out-paths",
                                "--out-link", str(pending / label),
                                source + "#packages." + system + "." + output + "^out")
                require(STORE.fullmatch(path), "Expected exactly one output path")
                require((pending / label).is_symlink() and os.readlink(pending / label) == path,
                        "Build did not register the requested output root")
                closure = json.loads(self.nix("path-info", "--recursive", "--json", path))
                paths = closure.keys() if isinstance(closure, dict) else [entry["path"] for entry in closure]
                paths = list(paths)
                require(path in paths and all(STORE.fullmatch(p) and Path(p).exists() for p in paths),
                        "Registered closure is incomplete")
                outputs[label] = {"path": path, "closure": sorted(paths)}
            command = declaration["command"]
            executable = outputs[command["output"]]["path"] + "/" + command["path"]
            require(os.access(executable, os.X_OK), "Workload executable missing")
            rootfs = outputs[declaration["rootfs"]]["path"]
            archive = rootfs if declaration.get("rootfsFormat") == "alpine-archive" else None
            if archive:
                require(archive.endswith(".tar.gz") and Path(archive).is_file(), "Expected an Alpine rootfs .tar.gz archive")
                shell = None
            else:
                shell = rootfs + "/bin/sh"
                require(Path(shell).is_symlink(), "Rootfs must provide the shared-store shell link")
            resolved = {"version": 1, "name": name, "system": system,
                        "source": {"revision": revision, "path": source, "narHash": nar_hash},
                        "declaration": declaration, "outputs": outputs,
                        "executable": executable, "shell": shell, "rootfsArchive": archive,
                        "executorSha256": hashlib.sha256(self.executor.read_bytes()).hexdigest()}
            if declaration["qualification"]["mode"] == "running":
                check_command = declaration["qualification"]["command"]
                check_executable = outputs[check_command["output"]]["path"] + "/" + check_command["path"]
                require(os.access(check_executable, os.X_OK), "Readiness executable missing")
                resolved["readinessExecutable"] = check_executable
            generation = hashlib.sha256(canonical(resolved).encode()).hexdigest()
            state = self.load(name)
            if state["generations"].get(generation, {}).get("status") == "stopped":
                prepared = state["generations"].get(state["prepared"], {})
                candidate = dict(prepared.get("manifest", {}))
                candidate.pop("retry", None)
                if candidate == resolved and prepared.get("status") != "stopped":
                    resolved = prepared["manifest"]
                    generation = state["prepared"]
                else:
                    resolved["retry"] = uuid.uuid4().hex
                    generation = hashlib.sha256(canonical(resolved).encode()).hexdigest()
            destination = root_parent / generation
            require(not destination.is_symlink(), "Invalid generation root directory")
            destination.mkdir(exist_ok=True)
            for label, output in outputs.items():
                link = destination / label
                if link.is_symlink():
                    require(os.readlink(link) == output["path"], "Generation roots differ")
                else:
                    require(not link.exists(), "Generation root is not a symlink")
                    # Native registration coordinates with a concurrently running GC.
                    subprocess.run(["nix-store", "--realise", "--add-root", str(link), output["path"]],
                                   check=True, stdout=subprocess.DEVNULL)
            shutil.rmtree(pending)
            state = self.load(name)
            previous = state["generations"].get(generation, {})
            state["generations"][generation] = {"manifest": resolved,
                "status": previous.get("status", "prepared") if state["active"] == generation else "prepared"}
            state["prepared"] = generation
            save(self.path(name), state)
            return {"generation": generation, "manifest": resolved}
        finally:
            if pending.exists():
                shutil.rmtree(pending)

    @staticmethod
    def validate(d, name, system):
        require(d.get("version") == 1 and d.get("name") == name and d.get("system") == system,
                "Workload schema, name or architecture mismatch")
        outputs = d.get("outputs")
        require(isinstance(outputs, dict) and outputs and "source" not in outputs, "Missing retained outputs")
        require(all(NAME.fullmatch(k) and isinstance(v, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", v)
                    for k, v in outputs.items()), "Unsafe output declaration")
        require(d.get("rootfs") in outputs, "Rootfs output is not retained")
        require(d.get("rootfsFormat", "busybox-probe") in ("busybox-probe", "alpine-archive"), "Unknown rootfs format")
        Controller.validate_command(d.get("command", {}), outputs)
        require(d.get("capabilities") == CAPABILITIES, "Unsupported guest capabilities")
        require(d.get("network") == "none", "Only isolated network=none is supported")
        qualification = d.get("qualification", {})
        mode = qualification.get("mode")
        require(mode in ("exit-success", "running") and
                isinstance(qualification.get("stdoutContains"), str) and qualification["stdoutContains"]
                and "\x00" not in qualification["stdoutContains"], "Invalid workload qualification")
        runtime = d.get("runtimeMaxSec")
        require(type(runtime) is int and (1 <= runtime <= 86400 or (mode == "running" and runtime == 0)),
                "Invalid workload timeout")
        if mode == "running":
            require(d.get("rootfsFormat") == "alpine-archive", "Managed shells currently require Alpine rootfs")
            Controller.validate_command(qualification.get("command", {}), outputs)
            timeout = qualification.get("timeoutSec")
            require(type(timeout) is int and 1 <= timeout <= 600, "Invalid readiness timeout")

    @staticmethod
    def validate_command(command, outputs):
        require(command.get("output") in outputs, "Executable output is not retained")
        path = command.get("path", "")
        require(isinstance(path, str) and re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", path)
                and all(part not in (".", "..") for part in path.split("/")), "Unsafe executable path")
        require(isinstance(command.get("args"), list) and all(isinstance(x, str) and "\x00" not in x
                for x in command["args"]), "Arguments must be strings without NUL")

    def generation(self, state, generation):
        require(generation and re.fullmatch(r"[a-f0-9]{64}", generation), "Invalid or missing generation")
        require(generation in state["generations"], "Unknown generation")
        return state["generations"][generation]

    def lifecycle(self, action, name, generation=None, target=None):
        state = self.load(name)
        if action == "inspect":
            return state
        if action == "summary":
            generation = state["active"]
            entry = state["generations"].get(generation, {})
            return {"name": name, "active": generation, "prepared": state["prepared"],
                    "status": entry.get("status", "stopped"), "bootId": state.get("target"),
                    "rootsRetained": bool(generation and (self.roots / name / generation).is_dir()),
                    "stateType": "owner-intent"}
        if action == "status-selection":
            return state["active"] or "none"
        if action == "mode":
            entry = self.generation(state, generation or state["prepared"])
            return entry["manifest"]["declaration"]["qualification"]["mode"]
        if action in ("begin-activate", "begin-stop"):
            require(isinstance(target, str) and re.fullmatch(r"[a-f0-9-]{36}", target), "Missing guest boot identity")
            require(not state["active"] or state.get("target") == target, "Guest boot identity changed; roots retained")
        if action == "begin-activate":
            generation = generation or state["prepared"]
            entry = self.generation(state, generation)
            require(state["active"] in (None, generation), "Stop the active generation before replacement")
            require(entry["status"] in ("prepared", "activating", "active"), "Prepare the stopped generation first")
            for label, output in entry["manifest"]["outputs"].items():
                link = self.roots / name / generation / label
                require(link.is_symlink() and os.readlink(link) == output["path"], "Generation root missing or changed")
            state["active"] = generation
            state["target"] = target
            entry["status"] = "activating"
        elif action == "active-generation":
            generation = generation or state["active"]
            entry = self.generation(state, generation)
            require(state["active"] == generation, "No matching active generation")
            return generation
        elif action == "confirm-active":
            entry = self.generation(state, generation)
            require(state["active"] == generation and entry["status"] == "activating", "No matching activation intent")
            entry["status"] = "active"
        elif action == "begin-stop":
            generation = generation or state["active"]
            entry = self.generation(state, generation)
            require(state["active"] == generation and entry["status"] in ("activating", "active", "stopping"),
                    "No matching active generation")
            entry["status"] = "stopping"
        elif action == "confirm-stopped":
            entry = self.generation(state, generation)
            require(state["active"] == generation and entry["status"] == "stopping", "No matching stop intent")
            # The transport calls this only after the guest confirms unit and container termination.
            roots = self.roots / name / generation
            require(roots.is_dir() and not roots.is_symlink(), "Invalid generation roots")
            require({p.name for p in roots.iterdir()} == set(entry["manifest"]["outputs"]),
                    "Unexpected generation root entries; roots retained")
            for label, output in entry["manifest"]["outputs"].items():
                link = roots / label
                require(link.is_symlink() and os.readlink(link) == output["path"], "Generation root changed")
            # Persist the acknowledgement before release; interrupted cleanup may only leak roots.
            entry["status"] = "stopped"
            state["active"] = None
            save(self.path(name), state)
            shutil.rmtree(roots)
        else:
            raise ValueError("Unknown lifecycle action")
        save(self.path(name), state)
        return generation

    def guest_script(self, action, name, generation):
        state = self.load(name)
        entry = self.generation(state, generation)
        require(state["active"] == generation, "Guest operation must match the active intent")
        expected = {"activate": ("activating",), "stop": ("stopping",), "check": ("active",), "status": ("activating", "active", "stopping"), "shell": ("active",)}
        require(action in expected and entry["status"] in expected[action], "Wrong guest operation state")
        m = entry["manifest"]
        if action == "activate":
            require(hashlib.sha256(self.executor.read_bytes()).hexdigest() == m["executorSha256"],
                    "Executor changed; prepare with the current executor before activation")
        unit = "nix-xd-" + name + "-" + generation[:32]
        q = shlex.quote
        header = "set -Eeuo pipefail\n" + "\n".join([
            "generation=" + q(generation), "unit=" + q(unit), "name=" + q(name),
            "system=" + q(m["system"]),
            'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + q(state["target"]),
            'test "$(id -u)" -ne 0',
            'test -n "${XDG_RUNTIME_DIR:-}" && test -d "$XDG_RUNTIME_DIR"',
            'run_dir="$XDG_RUNTIME_DIR/nix-xd-workloads/$name/$generation"',
            'test "$(podman info --format \'{{.Host.Security.Rootless}}\')" = true',
            'systemctl --user show-environment >/dev/null',
            'control_dir="$HOME/.local/state/nix-xd/workloads/$name"',
            'mkdir -p "$control_dir"',
            'exec 9>"$control_dir/lifecycle.lock"',
            'flock -x 9',
            'tombstone="$control_dir/$generation.stopped"',
            'container_exists() { local rc; if podman container exists "$unit"; then return 0; else rc=$?; [[ "$rc" == 1 ]] || exit "$rc"; return 1; fi; }',
        ]) + "\n"
        if action == "status":
            return header + r'''load="$(systemctl --user show "$unit.service" -p LoadState --value)" || [[ "$load" == not-found ]]
printf 'WORKLOAD_GENERATION=%s\nWORKLOAD_UNIT_LOAD=%s\n' "$generation" "$load"
systemctl --user show "$unit.service" -p ActiveState -p SubState -p Result -p MainPID || [[ "$load" == not-found ]]
running=false
if container_exists; then
  running="$(podman inspect "$unit" --format '{{.State.Running}}')"
  podman inspect "$unit" --format 'WORKLOAD_CONTAINER_ID={{.Id}}'
fi
printf 'WORKLOAD_CONTAINER_RUNNING=%s\n' "$running"
active="$(systemctl --user show "$unit.service" -p ActiveState --value)" || [[ "$load" == not-found ]]
if [[ "$active" == active && "$running" == true ]]; then
  printf 'WORKLOAD_HEALTH=running\n'
else
  printf 'WORKLOAD_HEALTH=not-running\n'
fi
printf 'WORKLOAD_STATUS_OK=%s\n' "$generation"
'''
        if action == "shell":
            require(m["declaration"]["qualification"]["mode"] == "running", "Shell requires a managed running workload")
            return header + r'''test ! -e "$tombstone"
test "$(systemctl --user show "$unit.service" -p ActiveState --value)" = active
container_exists
test "$(podman inspect "$unit" --format '{{.State.Running}}')" = true
flock -u 9
exec 9>&-
exec podman exec -it --user 1000:1000 "$unit" /bin/sh
'''
        if action == "check" and m["declaration"]["qualification"]["mode"] == "running":
            qualification = m["declaration"]["qualification"]
            command = [m["readinessExecutable"], *qualification["command"]["args"]]
            return header + 'deadline=$((SECONDS + ' + str(qualification["timeoutSec"]) + '))\n' + r'''while (( SECONDS < deadline )); do
  test ! -e "$tombstone"
  active="$(systemctl --user show "$unit.service" -p ActiveState --value)"
  [[ "$active" == active ]] || break
  if container_exists && [[ "$(podman inspect "$unit" --format '{{.State.Running}}')" == true ]]; then
''' + '    if podman exec "$unit" ' + shlex.join(command) + ' > "$run_dir/readiness.log" 2>&1; then\n' + r'''      cat "$run_dir/readiness.log"
''' + '      grep -F -- ' + q(qualification["stdoutContains"]) + ' "$run_dir/readiness.log"\n' + r'''      printf 'WORKLOAD_CHECKED=%s\n' "$generation"
      exit 0
    fi
  fi
  sleep 1
done
journalctl --user --no-pager -u "$unit.service" -o cat
exit 1
'''
        if action == "check":
            timeout = m["declaration"]["runtimeMaxSec"] + 5
            return header + 'deadline=$((SECONDS + ' + str(timeout) + '))\n' + r'''while (( SECONDS < deadline )); do
  active="$(systemctl --user show "$unit.service" -p ActiveState --value)"
  result="$(systemctl --user show "$unit.service" -p Result --value)"
  pid="$(systemctl --user show "$unit.service" -p MainPID --value)"
  [[ "$active" != failed && "$result" == success ]] || break
  [[ "$pid" != 0 ]] || break
  sleep 1
done
journalctl --user --no-pager -u "$unit.service" -o cat
[[ "$active" == active && "$result" == success && "$pid" == 0 ]]
test "$(systemctl --user show "$unit.service" -p ExecMainStatus --value)" = 0
''' + 'journalctl --user --no-pager -u "$unit.service" -o cat | grep -F -- ' + q(m["declaration"]["qualification"]["stdoutContains"]) + '\n' + r'''printf 'WORKLOAD_CHECKED=%s\n' "$generation"
'''
        if action == "stop":
            return header + '''touch "$tombstone"
load="$(systemctl --user show "$unit.service" -p LoadState --value)" || [[ "$load" == not-found ]]
if [[ "$load" != not-found ]]; then
  systemctl --user stop "$unit.service"
  active="$(systemctl --user show "$unit.service" -p ActiveState --value)" || [[ "$active" == inactive ]]
  [[ "$active" == inactive || "$active" == failed ]]
fi
if container_exists; then
  podman stop --time 10 "$unit" || { if container_exists; then exit 1; fi; }
  if container_exists; then
    test "$(podman inspect "$unit" --format '{{.State.Running}}')" = false
    podman rm "$unit"
  fi
fi
if container_exists; then exit 1; fi
rm -rf -- "$run_dir"
printf 'WORKLOAD_STOPPED=%s\\n' "$generation"
'''
        require(action == "activate", "Unknown guest action")
        d = m["declaration"]
        rootfs_arguments = ["--rootfs-archive", m["rootfsArchive"]] if m.get("rootfsArchive") else [m["shell"]]
        command = [*rootfs_arguments, m["executable"], *d["command"]["args"]]
        script = header + '''test ! -e "$tombstone"
case "$system:$(uname -m)" in
  aarch64-linux:aarch64|x86_64-linux:x86_64) ;;
  *) echo 'Guest architecture mismatch' >&2; exit 1 ;;
esac
findmnt -rn --mountpoint /var/mnt/nixstore >/dev/null
test "$(findmnt -rn -o FSTYPE --mountpoint /var/mnt/nixstore)" = 9p
options="$(findmnt -rn -o OPTIONS --mountpoint /var/mnt/nixstore)"
[[ ",$options," == *,ro,* ]]
'''
        for output in m["outputs"].values():
            for path in output["closure"]:
                script += "test -e " + q("/var/mnt/nixstore/" + path.removeprefix("/nix/store/")) + "\n"
        script += '''if [[ -f "$run_dir/generation" ]]; then
  test "$(cat "$run_dir/generation")" = "$generation"
  active="$(systemctl --user show "$unit.service" -p ActiveState --value)"
  result="$(systemctl --user show "$unit.service" -p Result --value)"
  [[ "$active" == active && "$result" == success ]] || { echo 'Existing activation needs stop/recovery' >&2; exit 1; }
else
  test "$(systemctl --user show "$unit.service" -p LoadState --value)" = not-found
  if container_exists; then exit 1; fi
  mkdir -p "$run_dir"
  chmod 700 "$run_dir"
  printf '%s\\n' "$generation" > "$run_dir/generation"
'''
        script += "  printf '%s' " + q(self.executor.read_text()) + ' > "$run_dir/executor"\n'
        script += ('  systemd-run --user --unit="$unit" --property=Type=exec '
                   '--property=RemainAfterExit=yes --property=Delegate=yes --property=RuntimeMaxSec=' + ('infinity' if d["runtimeMaxSec"] == 0 else str(d["runtimeMaxSec"]) + 's') + ' '
                   '/usr/bin/env NIX_XD_WORKLOAD_CONTAINER="$unit" /usr/bin/bash "$run_dir/executor" '
                   + shlex.join(command) + '\nfi\n')
        script += '''active="$(systemctl --user show "$unit.service" -p ActiveState --value)"
result="$(systemctl --user show "$unit.service" -p Result --value)"
[[ "$active" == active && "$result" == success ]]
printf 'WORKLOAD_INVOCATION_ID=%s\\n' "$(systemctl --user show "$unit.service" -p InvocationID --value)"
printf 'WORKLOAD_BOOT_ID=%s\\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'WORKLOAD_ACTIVATED=%s\\n' "$generation"
'''
        return script


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executor", required=True)
    parser.add_argument("--state", default="/nix/home/nixuser/.local/state/nix-xd/workloads")
    parser.add_argument("--roots", default="/nix/var/nix/gcroots/nix-xd/workloads")
    parser.add_argument("action", choices=["prepare", "inspect", "begin-activate", "confirm-active", "begin-stop", "confirm-stopped", "active-generation", "guest-activate", "guest-stop", "guest-check", "guest-status", "guest-shell", "status-selection", "mode", "summary"])
    parser.add_argument("--name", required=True)
    parser.add_argument("--system")
    parser.add_argument("--flake")
    parser.add_argument("--revision")
    parser.add_argument("--generation")
    parser.add_argument("--target")
    args = parser.parse_args()
    controller = Controller(args.state, args.roots, args.executor)
    with controller.locked(args.name):
        if args.action == "prepare":
            result = controller.prepare(args.name, args.system, args.flake, args.revision)
        elif args.action.startswith("guest-"):
            print(controller.guest_script(args.action.removeprefix("guest-"), args.name, args.generation), end="")
            return
        else:
            result = controller.lifecycle(args.action, args.name, args.generation, args.target)
        print(canonical(result).strip() if isinstance(result, dict) else result)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print("workload error: " + str(error), file=sys.stderr)
        sys.exit(1)
