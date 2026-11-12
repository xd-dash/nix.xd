#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash -n "$repo/bin/nix-xd-grants-import-credentials" "$repo/bin/nix-xd-grants-transport-qualify"
python3 - "$repo" <<'PY'
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1])
fixture = {
    "schema": 1, "scope": "native-qualifier", "grants": [
        {"volume": "nix-xd-state-secret-native-ssh-qualification",
         "destination": "/run/nix-xd/mounts/secrets", "access": "ro",
         "writer": "ssh-owner", "reader": "native-qualifier"},
        {"volume": "nix-xd-state-control-native-qualification-evidence",
         "destination": "/run/nix-xd/mounts/evidence", "access": "rw",
         "writer": "native-qualifier", "reader": "native-qualifier"}
    ]
}
with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory, "grants.json")
    path.write_text(json.dumps(fixture))
    result = subprocess.run(["python3", str(root / "lib/runtime_grants.py"),
                             "fixture", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
      "nix-xd-state-secret-native-ssh-qualification "
      "nix-xd-state-control-native-qualification-evidence native-qualifier")
    fixture["grants"][0]["access"] = "rw"
    path.write_text(json.dumps(fixture))
    denied = subprocess.run(["python3", str(root / "lib/runtime_grants.py"),
                             "fixture", str(path)], capture_output=True)
    assert denied.returncode != 0

runner = (root / "bin/nix-xd-grants-transport-qualify").read_text()
assert '--network "container:$guest"' in runner
assert '--mount "type=volume,src=$store,dst=/nix,ro"' in runner
assert '$secret:/run/nix-xd/mounts/secrets:ro,z' in runner
assert 'NIX_XD_TRANSPORT_KNOWN_HOSTS=' in runner
assert "NIX_XD_NATIVE_ARTIFACT=" in runner
assert "podman cp" not in runner
importer = (root / "bin/nix-xd-grants-import-credentials").read_text()
assert 'Credential volume not empty; refusing import' in importer
assert '"$cid:/ssh/identity"' in importer
assert 'chmod 0600 /ssh/identity' in importer
print("GRANTS_NATIVE_TRANSPORT_STATIC=passed")
PY
