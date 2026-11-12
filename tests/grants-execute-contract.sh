#!/usr/bin/env bash
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash -n "$repo/bin/nix-xd-grants-execute"
python3 - "$repo" <<'PY'
import importlib.util
import json
import pathlib
import tempfile

root = pathlib.Path(__import__("sys").argv[1])
spec = importlib.util.spec_from_file_location("runtime_grants", root / "lib/runtime_grants.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

good = {
    "schema": 1,
    "scope": "qualifier",
    "grants": [
        {"volume": "nix-xd-state-secret-example-qualification",
         "destination": "/run/nix-xd/mounts/secrets",
         "access": "ro", "writer": "secrets-owner", "reader": "qualifier"},
        {"volume": "nix-xd-state-control-example-qualification-evidence",
         "destination": "/run/nix-xd/mounts/evidence",
         "access": "rw", "writer": "qualifier", "reader": "qualifier"},
    ],
}
with tempfile.TemporaryDirectory() as name:
    file = pathlib.Path(name) / "grants.json"
    file.write_text(json.dumps(good))
    parsed = module.load(file)
    assert len(parsed["grants"]) == 2
    assert "nix-xd-state-secret-example-qualification" in module.mounts(parsed)
    result = __import__("subprocess").check_output(
        ["python3", str(root / "lib/runtime_grants.py"), "fixture", str(file)],
        text=True,
    ).strip()
    assert result == ("nix-xd-state-secret-example-qualification "
                      "nix-xd-state-control-example-qualification-evidence qualifier")

    good["grants"][0]["access"] = "rw"
    file.write_text(json.dumps(good))
    try:
        module.load(file)
    except ValueError:
        pass
    else:
        raise AssertionError("Unexpected writable private identity grant")
print("GRANTS_EXECUTE_STATIC=passed")
PY
