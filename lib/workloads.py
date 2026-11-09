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
            state["generations"][generation] = (dict(previous, manifest=resolved) if state["active"] == generation
                else {"manifest": resolved, "status": "prepared"})
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
        placement = d.get("placement", "guest")
        require(placement in ("host", "guest"), "Invalid workload placement")
        expected_caps = ["store-bind-ro", "user-systemd", "rootless-podman"] if placement == "host" else CAPABILITIES
        require(d.get("capabilities") == expected_caps, "Unsupported placement capabilities")
        require(d.get("storeDomain", "common") == "common", "This runtime currently provisions only the common store domain")
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

    def batch(self, requests):
        require(isinstance(requests, list) and 1 <= len(requests) <= 6, "Invalid batch size")
        names = [request.get("name", "") for request in requests]
        require(len(set(names)) == len(names) and all(NAME.fullmatch(name) for name in names), "Invalid batch names")
        results = {}
        for request in requests:
            name = request["name"]
            with self.locked(name):
                action = request.get("action")
                require(action in ("inspect", "roots", "isolation"), "Unsupported batch action")
                state = self.load(name)
                if action == "inspect":
                    results[name] = state
                    continue
                generation = state["active"]
                fingerprint = self.lifecycle("assert-retained", name, generation)
                result = {"generation": generation, "fingerprint": fingerprint}
                if action == "isolation":
                    result["script"] = self.guest_script("isolation", name, generation,
                        request.get("token"), request.get("mode"))
                results[name] = result
        return results

    def generation(self, state, generation):
        require(generation and re.fullmatch(r"[a-f0-9]{64}", generation), "Invalid or missing generation")
        require(generation in state["generations"], "Unknown generation")
        return state["generations"][generation]

    def lifecycle(self, action, name, generation=None, target=None, store_export=None):
        state = self.load(name)
        if action == "inspect":
            return state
        if action == "summary":
            generation = state["active"]
            entry = state["generations"].get(generation, {})
            return {"name": name, "active": generation, "prepared": state["prepared"],
                    "status": entry.get("status", "stopped"), "bootId": state.get("target"),
                    "rootsRetained": bool(generation and (self.roots / name / generation).is_dir()),
                    "stateType": "owner-intent", "instance": entry.get("instance"),
                    "recreation": entry.get("recreation")}
        if action == "status-selection":
            return state["active"] or "none"
        if action == "pending-recreation":
            generation = generation or state["active"]
            entry = self.generation(state, generation)
            require(entry["status"].startswith("recreating-"), "No pending recreation")
            return entry["recreation"]["id"]
        if action == "runtime-path":
            generation = generation or state["active"]
            entry = self.generation(state, generation)
            suffix = "/" + entry["instance"] if entry.get("instance") else ""
            return name + "/" + generation + suffix
        if action in ("placement", "container-name"):
            generation = generation or state["active"] or state["prepared"]
            entry = self.generation(state, generation)
            if action == "placement":
                return entry["manifest"]["declaration"].get("placement", "guest")
            instance = entry.get("instance")
            identity = generation[:16] + "-" + instance[:16] if instance else generation[:32]
            return "nix-xd-" + name + "-" + identity
        if action == "assert-target":
            require(state.get("target") == target and state["active"], "Runtime boot identity differs from active workload")
            return state["active"]
        if action == "assert-retained":
            generation = generation or state["active"]
            require(state["active"] == generation, "No active rooted workload")
            return self.assert_retained(state, name, generation)
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
            if entry["manifest"]["declaration"].get("placement", "guest") == "host":
                require(isinstance(store_export, str) and store_export.startswith("/") and ".." not in store_export and "\n" not in store_export,
                        "Missing validated host store export")
                require(not state["active"] or state.get("storeExport") == store_export, "Active store export changed")
                state["storeExport"] = store_export
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

    def assert_retained(self, state, name, generation):
        entry = self.generation(state, generation)
        roots = self.roots / name / generation
        require(roots.is_dir() and not roots.is_symlink(), "Generation roots missing")
        links = {}
        for label, output in entry["manifest"]["outputs"].items():
            link = roots / label
            require(link.is_symlink() and os.readlink(link) == output["path"] and Path(output["path"]).exists(),
                    "Generation root missing or changed")
            links[label] = output["path"]
        return hashlib.sha256(canonical(links).encode()).hexdigest()

    def recreation(self, action, name, generation=None, target=None, transaction=None, evidence=None):
        state = self.load(name)
        generation = generation or state["active"]
        entry = self.generation(state, generation)
        require(state["active"] == generation, "Recreation requires the active generation")
        require(entry["manifest"]["declaration"]["qualification"]["mode"] == "running" and
                entry["manifest"]["declaration"].get("rootfsFormat") == "alpine-archive",
                "Recreation requires a running Alpine environment")
        fingerprint = self.assert_retained(state, name, generation)
        if action == "begin-recreate":
            require(target == state.get("target"), "Guest boot identity changed; roots retained")
            require(hashlib.sha256(self.executor.read_bytes()).hexdigest() == entry["manifest"]["executorSha256"],
                    "Executor differs from the active generation; stop and prepare a new generation instead")
            if entry["status"] == "active":
                entry["recreation"] = {"id": uuid.uuid4().hex, "oldInstance": entry.get("instance"),
                    "newInstance": uuid.uuid4().hex, "rootsFingerprint": fingerprint}
                entry["status"] = "recreating-stop"
            else:
                require(entry["status"].startswith("recreating-"), "Another lifecycle operation is in progress")
            save(self.path(name), state)
            return entry["recreation"]["id"]
        recreation = entry.get("recreation", {})
        require(transaction == recreation.get("id") and transaction, "Recreation transaction mismatch")
        require(fingerprint == recreation["rootsFingerprint"], "Recreation roots changed")
        if action == "recreate-phase":
            if entry["status"] == "recreating-stop":
                return "stop" if "before" in recreation else "snapshot"
            return {"recreating-start": "start", "recreating-check": "check",
                    "recreating-verify": "verify", "active": "done"}.get(entry["status"], "blocked")
        if action in ("recreate-record-before", "recreate-record-after"):
            stage = "before" if action.endswith("before") else "after"
            expected_status = "recreating-stop" if stage == "before" else "recreating-verify"
            require(entry["status"] == expected_status, "Wrong recreation snapshot phase")
            values = self.parse_recreation_evidence(evidence)
            require(values["GENERATION"] == generation and values["BOOT_ID"] == state["target"] and
                    values["TRANSACTION"] == transaction, "Snapshot identity mismatch")
            expected_instance = recreation["oldInstance"] if stage == "before" else recreation["newInstance"]
            require(values["INSTANCE"] == (expected_instance or "legacy"), "Snapshot instance mismatch")
            require(values["WRITABLE_STATE"] == ("marked" if stage == "before" else "fresh"), "Writable state was not recreated")
            require(stage not in recreation or recreation[stage] == values, "Recorded snapshot changed")
            recreation[stage] = values
        elif action == "recreate-stopped":
            require(entry["status"] == "recreating-stop" and "before" in recreation, "Missing old-instance snapshot")
            entry["instance"] = recreation["newInstance"]
            entry["status"] = "recreating-start"
        elif action == "recreate-activated":
            require(entry["status"] == "recreating-start", "No replacement activation intent")
            entry["status"] = "recreating-check"
        elif action == "recreate-checked":
            require(entry["status"] == "recreating-check", "Replacement readiness not pending")
            entry["status"] = "recreating-verify"
        elif action == "confirm-recreated":
            require(entry["status"] == "recreating-verify" and "after" in recreation, "Replacement snapshot missing")
            before, after = recreation["before"], recreation["after"]
            require(before["CONTAINER_ID"] != after["CONTAINER_ID"], "Container was not replaced")
            for key in ("GENERATION", "BOOT_ID", "NIX_PATH", "HELLO_PATH", "NIX_VERSION"):
                require(before[key] == after[key], "Recreation changed " + key)
            entry["status"] = "active"
            recreation["result"] = "passed"
        elif action == "abandon-recreate":
            require(entry["status"].startswith("recreating-"), "No pending recreation")
            entry["status"] = "stopping"
            recreation["result"] = "abandoning"
        else:
            raise ValueError("Unknown recreation action")
        save(self.path(name), state)
        return generation

    @staticmethod
    def parse_recreation_evidence(text):
        expected = {"GENERATION", "BOOT_ID", "TRANSACTION", "INSTANCE", "CONTAINER_ID", "NIX_PATH",
                    "HELLO_PATH", "NIX_VERSION", "METADATA_QUERY", "WRITABLE_STATE"}
        values = {}
        for line in text.splitlines():
            if not line.startswith("RECREATE_"):
                continue
            key, value = line.removeprefix("RECREATE_").split("=", 1)
            require(key in expected and key not in values and value, "Invalid recreation snapshot field")
            values[key] = value
        require(set(values) == expected and values["METADATA_QUERY"] == "passed", "Incomplete recreation snapshot")
        require(re.fullmatch(r"[a-f0-9]{64}", values["CONTAINER_ID"]), "Invalid container identity")
        require(STORE.fullmatch(values["HELLO_PATH"]) and
                re.fullmatch(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+/bin/nix", values["NIX_PATH"]),
                "Invalid snapshot store paths")
        return values

    @staticmethod
    def container_recreation_probe(stage, transaction):
        require(stage in ("before", "after") and re.fullmatch(r"[a-f0-9]{32}", transaction), "Invalid recreation probe")
        return "set -eu\ntransaction=" + shlex.quote(transaction) + "\n" + r'''test "$(id -u)" = 1000
home_probe="$HOME/.nix-xd-recreate-$transaction"
db_probe="/nix/var/nix/.nix-xd-recreate-$transaction"
''' + (r'''umask 077
for probe in "$home_probe" "$db_probe"; do
  test ! -e "$probe" || test "$(cat "$probe")" = "$transaction"
  printf '%s\n' "$transaction" > "$probe"
done
printf 'RECREATE_WRITABLE_STATE=marked\n'
''' if stage == "before" else r'''test ! -e "$home_probe"
test ! -e "$db_probe"
printf 'RECREATE_WRITABLE_STATE=fresh\n'
''') + r'''grep -Eq ' /nix/store ro(,| )' /proc/self/mountinfo
nix_path="$(readlink /usr/local/bin/nix)"
hello_path="$(readlink /usr/local/bin/hello)"
hello_path="${hello_path%/bin/hello}"
nix path-info "$hello_path" >/dev/null
nix-store --query --requisites "$hello_path" >/dev/null
printf 'RECREATE_NIX_PATH=%s\nRECREATE_HELLO_PATH=%s\n' "$nix_path" "$hello_path"
printf 'RECREATE_NIX_VERSION=%s\n' "$(nix --version)"
printf 'RECREATE_METADATA_QUERY=passed\n'
'''

    def guest_script(self, action, name, generation, isolation_token=None, isolation_mode=None):
        state = self.load(name)
        entry = self.generation(state, generation)
        require(state["active"] == generation, "Guest operation must match the active intent")
        expected = {"activate": ("activating",), "stop": ("stopping",), "check": ("active",), "status": ("activating", "active", "stopping", "recreating-stop", "recreating-start", "recreating-check", "recreating-verify"), "shell": ("active",),
                    "recreate-stop": ("recreating-stop",), "recreate-activate": ("recreating-start",),
                    "recreate-check": ("recreating-check",), "snapshot-before": ("recreating-stop",),
                    "snapshot-after": ("recreating-verify",), "isolation": ("active",)}
        require(action in expected and entry["status"] in expected[action], "Wrong guest operation state")
        m = entry["manifest"]
        host = m["declaration"].get("placement", "guest") == "host"
        export_root = state["storeExport"] if host else "/var/mnt/nixstore"
        if action in ("activate", "recreate-activate"):
            require(hashlib.sha256(self.executor.read_bytes()).hexdigest() == m["executorSha256"],
                    "Executor changed; prepare with the current executor before activation")
        instance = entry.get("instance")
        identity = generation[:16] + "-" + instance[:16] if instance else generation[:32]
        unit = "nix-xd-" + name + "-" + identity
        runtime_suffix = name + "/" + generation + ("/" + instance if instance else "")
        tombstone = generation + ("." + instance if instance else "") + ".stopped"
        q = shlex.quote
        header = "set -Eeuo pipefail\n" + "\n".join([
            "generation=" + q(generation), "unit=" + q(unit), "name=" + q(name),
            "system=" + q(m["system"]),
            'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + q(state["target"]),
            'test "$(id -u)" -ne 0',
            'test -n "${XDG_RUNTIME_DIR:-}" && test -d "$XDG_RUNTIME_DIR"',
            'run_dir="$XDG_RUNTIME_DIR/nix-xd-workloads/"' + q(runtime_suffix),
            'test "$(podman info --format \'{{.Host.Security.Rootless}}\')" = true',
            'systemctl --user show-environment >/dev/null',
            'control_dir="$HOME/.local/state/nix-xd/workloads/$name"',
            'mkdir -p "$control_dir"',
            'exec 9>"$control_dir/lifecycle.lock"',
            'flock -x 9',
            'tombstone="$control_dir/"' + q(tombstone),
            'container_exists() { local rc; if podman container exists "$unit"; then return 0; else rc=$?; [[ "$rc" == 1 ]] || exit "$rc"; return 1; fi; }',
        ]) + "\n"
        if action == "isolation":
            require(isolation_mode in ("write", "check") and re.fullmatch(r"[a-f0-9]{32}", isolation_token or ""), "Invalid isolation probe")
            probe = "set -eu\nlabel=" + q(name) + "\ntoken=" + q(isolation_token) + "\n" + r'''test "$(id -u)" = 1000
for directory in "$HOME" /nix/var/nix "$XDG_RUNTIME_DIR" /tmp; do
  file="$directory/.nix-xd-isolation-$token"
''' + ("  umask 077; printf '%s\\n' \"$label\" > \"$file\"\n" if isolation_mode == "write" else '') + r'''  test "$(cat "$file")" = "$label"
done
grep -Eq ' /nix/store ro(,| )' /proc/self/mountinfo
hello="$(readlink /usr/local/bin/hello)"
hello="${hello%/bin/hello}"
nix path-info "$hello" >/dev/null
printf 'ISOLATION_NIX_PATH=%s\nISOLATION_HELLO_PATH=%s\n' "$(readlink /usr/local/bin/nix)" "$hello"
printf 'ISOLATION_PID_NAMESPACE=%s\n' "$(readlink /proc/1/ns/pid)"
printf 'ISOLATION_STATE=private\nISOLATION_STORE=read-only\n'
'''
            return header + r'''container_exists
test "$(podman inspect "$unit" --format '{{.State.Running}}')" = true
printf 'ISOLATION_BOOT_ID=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'ISOLATION_CONTAINER_ID=%s\n' "$(podman inspect "$unit" --format '{{.Id}}')"
''' + "printf '%s' " + q(probe) + ' > "$run_dir/isolation.sh"\n' + 'podman exec -i "$unit" /bin/sh -s < "$run_dir/isolation.sh"\n' + "printf 'WORKLOAD_ISOLATION_OK=%s\\n' \"$generation\"\n"
        if action.startswith("snapshot-"):
            stage = "before" if action == "snapshot-before" else "after"
            transaction = entry["recreation"]["id"]
            probe = self.container_recreation_probe(stage, transaction)
            return header + 'test ! -e "$tombstone"\ncontainer_exists\n' + r'''test "$(podman inspect "$unit" --format '{{.State.Running}}')" = true
printf 'RECREATE_BOOT_ID=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'RECREATE_CONTAINER_ID=%s\n' "$(podman inspect "$unit" --format '{{.Id}}')"
printf 'RECREATE_GENERATION=%s\n' "$generation"
''' + "printf 'RECREATE_TRANSACTION=%s\n' " + q(transaction) + "\n" + "printf 'RECREATE_INSTANCE=%s\n' " + q(instance or "legacy") + "\n" + "printf '%s' " + q(probe) + ' > "$run_dir/recreate-probe.sh"\n' + 'podman exec -i "$unit" /bin/sh -s < "$run_dir/recreate-probe.sh"\n'
        action = {"recreate-stop": "stop", "recreate-activate": "activate", "recreate-check": "check"}.get(action, action)
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
rm -f -- "$run_dir/executor" "$run_dir/generation" "$run_dir/readiness.log" "$run_dir/shell.sh" "$run_dir/recreate-probe.sh" "$run_dir/isolation.sh"
rmdir "$run_dir" 2>/dev/null || true
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
'''
        if host:
            script += "test -d " + q(export_root) + "\n"
        else:
            script += '''findmnt -rn --mountpoint /var/mnt/nixstore >/dev/null
test "$(findmnt -rn -o FSTYPE --mountpoint /var/mnt/nixstore)" = 9p
options="$(findmnt -rn -o OPTIONS --mountpoint /var/mnt/nixstore)"
[[ ",$options," == *,ro,* ]]
'''
        for output in m["outputs"].values():
            for path in output["closure"]:
                script += "test -e " + q(export_root + "/" + path.removeprefix("/nix/store/")) + "\n"
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
                   '/usr/bin/env NIX_XD_WORKLOAD_CONTAINER="$unit" ' +
                   ('NIX_XD_STORE_TRANSPORT=bind NIX_XD_STORE_EXPORT=' + q(export_root) + ' ' if host else '') +
                   '/usr/bin/bash "$run_dir/executor" '
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
    parser.add_argument("action", choices=["batch", "prepare", "inspect", "begin-activate", "confirm-active", "begin-stop", "confirm-stopped", "active-generation", "guest-activate", "guest-stop", "guest-check", "guest-status", "guest-shell", "status-selection", "mode", "summary", "runtime-path", "pending-recreation", "placement", "container-name", "assert-target", "assert-retained", "guest-isolation",
        "begin-recreate", "recreate-phase", "recreate-record-before", "recreate-record-after", "recreate-stopped",
        "recreate-activated", "recreate-checked", "confirm-recreated", "abandon-recreate",
        "guest-recreate-stop", "guest-recreate-activate", "guest-recreate-check", "guest-snapshot-before", "guest-snapshot-after"])
    parser.add_argument("--name")
    parser.add_argument("--system")
    parser.add_argument("--flake")
    parser.add_argument("--revision")
    parser.add_argument("--generation")
    parser.add_argument("--target")
    parser.add_argument("--store-export")
    parser.add_argument("--isolation-token")
    parser.add_argument("--isolation-mode")
    parser.add_argument("--transaction")
    args = parser.parse_args()
    controller = Controller(args.state, args.roots, args.executor)
    if args.action == "batch":
        print(canonical(controller.batch(json.load(sys.stdin))), end="")
        return
    require(NAME.fullmatch(args.name or ""), "Missing or invalid workload name")
    with controller.locked(args.name):
        if args.action == "prepare":
            result = controller.prepare(args.name, args.system, args.flake, args.revision)
        elif args.action in ("begin-recreate", "recreate-phase", "recreate-record-before", "recreate-record-after",
                             "recreate-stopped", "recreate-activated", "recreate-checked", "confirm-recreated", "abandon-recreate"):
            evidence = sys.stdin.read() if args.action.startswith("recreate-record-") else None
            result = controller.recreation(args.action, args.name, args.generation, args.target, args.transaction, evidence)
        elif args.action.startswith("guest-"):
            print(controller.guest_script(args.action.removeprefix("guest-"), args.name, args.generation, args.isolation_token, args.isolation_mode), end="")
            return
        else:
            result = controller.lifecycle(args.action, args.name, args.generation, args.target, args.store_export)
        print(canonical(result).strip() if isinstance(result, dict) else result)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print("workload error: " + str(error), file=sys.stderr)
        sys.exit(1)
