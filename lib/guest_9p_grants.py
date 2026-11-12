#!/usr/bin/env python3
"""Plan read-only 9P exports from existing labeled Podman volumes."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
VOLUME = re.compile(r"nix-xd-state-(control|vm|application|secret)-([a-z][a-z0-9-]{0,39})")
TAG = re.compile(r"[a-z][a-z0-9-]{0,30}")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    data = json.loads(Path(path).read_text())
    require(type(data) is dict and set(data) == {"schema", "guest", "exports"}, "Invalid 9P manifest")
    require(data["schema"] == 1 and type(data["guest"]) is str and NAME.fullmatch(data["guest"]), "Invalid guest")
    exports = data["exports"]
    require(type(exports) is list and bool(exports), "At least one 9P export required")
    names, tags = set(), set()
    for entry in exports:
        require(type(entry) is dict and set(entry) == {"volume", "tag", "access"}, "Invalid export fields")
        volume, tag = entry["volume"], entry["tag"]
        require(type(volume) is str and VOLUME.fullmatch(volume), "Unexpected state volume")
        require(type(tag) is str and TAG.fullmatch(tag) and tag != "nixstore", "Invalid or reserved 9P tag")
        require(entry["access"] == "ro", "9P data exports must initially be read-only")
        require(volume not in names and tag not in tags, "Duplicate 9P export")
        names.add(volume)
        tags.add(tag)
    return data


def preflight(data, machine):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", machine), "Invalid Podman Machine")
    prefix = ["podman", "--connection", machine]
    for entry in data["exports"]:
        volume = entry["volume"]
        kind, name = VOLUME.fullmatch(volume).groups()
        label_data = subprocess.check_output(
            prefix + ["volume", "inspect", volume, "--format", "{{json .Labels}}"], text=True
        )
        labels = json.loads(label_data)
        require(labels.get("io.nix-xd.state.version") == "1" and
                labels.get("io.nix-xd.state.kind") == kind and
                labels.get("io.nix-xd.state.name") == name,
                "Unowned or mismatched 9P volume " + volume)
        print("GUEST_9P_VOLUME=verified volume=" + volume + " tag=" + entry["tag"])
    print("GUEST_9P_PREFLIGHT=passed guest=" + data["guest"] + " data_mounted=false")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "preflight", "pairs"))
    parser.add_argument("manifest")
    parser.add_argument("--machine", default="")
    options = parser.parse_args()
    data = load(options.manifest)
    if options.action == "pairs":
        for entry in data["exports"]:
            print(entry["volume"] + " " + entry["tag"])
    elif options.action == "plan":
        for entry in data["exports"]:
            print("GUEST_9P_GRANT=" + entry["volume"] + " tag=" +
                  entry["tag"] + " access=ro")
        print("GUEST_9P_PLAN=passed guest=" + data["guest"])
    else:
        require(options.machine, "Provide Podman Machine")
        preflight(data, options.machine)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print("9P grant error: " + str(error), file=sys.stderr)
        sys.exit(1)
