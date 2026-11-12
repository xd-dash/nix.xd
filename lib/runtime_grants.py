#!/usr/bin/env python3
"""Validate workload-selected state-volume grants without reading volume contents."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

IDENTITY = re.compile(r"[a-z][a-z0-9-]{0,39}")
VOLUME = re.compile(r"nix-xd-state-(control|vm|application)-([a-z][a-z0-9-]{0,39})")
MOUNT = re.compile(r"/run/nix-xd/mounts/([a-z][a-z0-9-]{0,39})")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def load(path):
    record = json.loads(Path(path).read_text())
    require(type(record) is dict and record.get("schema") == 1, "Invalid grant schema")
    require(set(record) == {"schema", "scope", "grants"}, "Unexpected grant document fields")
    scope = record["scope"]
    require(type(scope) is str and IDENTITY.fullmatch(scope), "Invalid grant scope")
    grants = record["grants"]
    require(type(grants) is list and bool(grants), "Expected explicit nonempty grant list")
    seen_paths = set()
    writers = {}
    for grant in grants:
        require(type(grant) is dict and set(grant) == {
            "volume", "destination", "access", "writer", "reader"
        }, "Invalid grant fields")
        volume = grant["volume"]
        require(type(volume) is str and VOLUME.fullmatch(volume), "Only labeled state volumes may be granted")
        destination = grant["destination"]
        require(type(destination) is str and MOUNT.fullmatch(destination), "Invalid runtime grant destination")
        require(destination not in seen_paths, "Duplicate grant destination")
        seen_paths.add(destination)
        reader = grant["reader"]
        writer = grant["writer"]
        require(all(type(value) is str and IDENTITY.fullmatch(value) for value in (reader, writer)),
                "Invalid grant reader or writer")
        require(reader == scope, "Grant reader must match selected runtime scope")
        access = grant["access"]
        require(access in ("ro", "rw"), "Grant access must be ro or rw")
        if access == "rw":
            require(reader == writer, "Only declared writer may receive writable grant")
            require(volume not in writers, "Multiple writers for same volume")
            writers[volume] = writer
    return record


def mounts(record):
    return " ".join(
        grant["volume"] + ":" + grant["destination"] + ":" + grant["access"]
        for grant in record["grants"]
    )


def verify(record, machine, scope):
    require(record["scope"] == scope, "Runtime scope differs from declared reader")
    require(IDENTITY.fullmatch(scope), "Invalid runtime scope")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", machine), "Invalid Podman machine")
    podman = ["podman", "--connection", machine]
    raw = subprocess.check_output(podman + ["inspect", scope], text=True)
    containers = json.loads(raw)
    require(len(containers) == 1, "Expected one Nix-Alpine runtime")
    actual = containers[0].get("Mounts", [])
    expected_paths = {grant["destination"] for grant in record["grants"]}
    actual_grants = {m.get("Destination") for m in actual
                     if str(m.get("Destination", "")).startswith("/run/nix-xd/mounts/")}
    require(actual_grants == expected_paths,
            "Active runtime grants differ from selected declaration")
    for grant in record["grants"]:
        volume = grant["volume"]
        label_raw = subprocess.check_output(
            podman + ["volume", "inspect", volume, "--format", "{{json .Labels}}"], text=True
        )
        labels = json.loads(label_raw)
        match = VOLUME.fullmatch(volume)
        require(labels.get("io.nix-xd.state.version") == "1" and
                labels.get("io.nix-xd.state.kind") == match.group(1) and
                labels.get("io.nix-xd.state.name") == match.group(2),
                "State volume does not carry declared ownership: " + volume)
        relevant = [m for m in actual if m.get("Destination") == grant["destination"]]
        require(len(relevant) == 1 and relevant[0].get("Type") == "volume" and
                relevant[0].get("Name") == volume and
                relevant[0].get("RW") is (grant["access"] == "rw"),
                "Active runtime mount does not match grant: " + grant["destination"])
        subprocess.run(podman + ["exec", scope, "test", "-r", grant["destination"]],
                       check=True, stdout=subprocess.DEVNULL)
        if grant["access"] == "rw":
            ids = subprocess.check_output(podman + ["ps", "-aq"], text=True).split()
            for identity in ids:
                if identity == containers[0].get("Id"):
                    continue
                peer = json.loads(subprocess.check_output(
                    podman + ["inspect", identity], text=True
                ))[0]
                require(not any(m.get("Name") == volume and m.get("RW") is True
                                for m in peer.get("Mounts", [])),
                        "Another container has writable access to " + volume)
        print("RUNTIME_GRANT_VERIFIED=" + grant["destination"] + " access=" + grant["access"])
    print("RUNTIME_GRANTS_RESULT=passed scope=" + scope)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "render", "verify"))
    parser.add_argument("manifest")
    parser.add_argument("--machine", default="")
    parser.add_argument("--scope", default="")
    args = parser.parse_args()
    record = load(args.manifest)
    if args.action == "render":
        print(mounts(record))
    elif args.action == "plan":
        print("RUNTIME_GRANT_PLAN=passed scope=" + record["scope"] +
              " grants=" + str(len(record["grants"])))
        for grant in record["grants"]:
            print("RUNTIME_GRANT=" + grant["volume"] + " destination=" +
                  grant["destination"] + " access=" + grant["access"] +
                  " writer=" + grant["writer"])
    else:
        require(args.machine and args.scope, "Provide --machine and --scope for live verification")
        verify(record, args.machine, args.scope)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print("Runtime grant error: " + str(error), file=sys.stderr)
        sys.exit(1)
