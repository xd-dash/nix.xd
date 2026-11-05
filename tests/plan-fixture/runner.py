#!/usr/bin/env python3
"""Synthetic protocol fixture only; application modules belong to their owners."""
import argparse
import json
import sys
from pathlib import Path


def execute(plan, gate):
    if plan.get("schemaVersion") != 2 or plan.get("protocolVersion") != 1:
        raise ValueError("unsupported schema or protocol version")
    modules = plan.get("modules")
    gates = plan.get("gates")
    if not isinstance(modules, list) or not isinstance(gates, dict):
        raise ValueError("invalid modules or gates")
    indexed = {}
    for module in modules:
        module_id = module.get("id")
        if not isinstance(module_id, str) or not module_id or module_id in indexed:
            raise ValueError("duplicate or missing module ID")
        if module.get("kind") != "fixture.step":
            raise ValueError("unknown module kind: " + str(module.get("kind")))
        if module.get("phases") != ["prepare", "execute", "verify", "cleanup"]:
            raise ValueError("unexpected module phases")
        if module.get("cleanup") != "always":
            raise ValueError("fixture modules must clean up")
        if not isinstance(module.get("inputs"), dict):
            raise ValueError("module inputs must be an object")
        if not isinstance(module.get("outputs"), list):
            raise ValueError("module outputs must be a list")
        if not isinstance(module.get("dependsOn"), list):
            raise ValueError("module dependencies must be a list")
        indexed[module_id] = module
    if gate not in gates or not isinstance(gates[gate], list) or not gates[gate]:
        raise ValueError("unknown or empty gate: " + gate)

    visit_state = {}
    order = []

    def visit(module_id):
        if module_id not in indexed:
            raise ValueError("unknown dependency: " + str(module_id))
        state = visit_state.get(module_id, 0)
        if state == 1:
            raise ValueError("dependency cycle at " + module_id)
        if state == 2:
            return
        visit_state[module_id] = 1
        for dependency in indexed[module_id]["dependsOn"]:
            visit(dependency)
        visit_state[module_id] = 2
        order.append(module_id)

    for entry in gates[gate]:
        visit(entry)

    evidence = []
    started = []
    failure = None
    try:
        for module_id in order:
            module = indexed[module_id]
            started.append(module_id)
            for phase in ("prepare", "execute", "verify"):
                evidence.append({"module": module_id, "phase": phase, "status": "pass"})
                if phase == "execute" and module["inputs"].get("fail"):
                    raise RuntimeError("injected failure: " + module_id)
            for output in module["outputs"]:
                if not isinstance(output, str):
                    raise ValueError("output name must be a string")
                evidence.append({"module": module_id, "output": output, "value": "verified"})
    except (RuntimeError, ValueError) as exc:
        failure = str(exc)
    finally:
        for module_id in reversed(started):
            evidence.append({"module": module_id, "phase": "cleanup", "status": "pass"})

    return {"status": "failed" if failure else "passed", "gate": gate,
            "order": order, "events": evidence, "error": failure}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--workspaces", required=True)
    parser.add_argument("--toolbox", required=True)
    parser.add_argument("--nix-alpine-local", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--plan-checkout", required=True)
    args = parser.parse_args()
    plan_root = Path(args.workspaces) / args.plan_checkout
    plan_file = Path(args.plan).resolve()
    if not plan_file.is_relative_to(plan_root.resolve()):
        parser.error("plan must be inside its declared checkout")
    with plan_file.open(encoding="utf-8") as handle:
        plan = json.load(handle)
    try:
        evidence = execute(plan, args.gate)
    except ValueError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        return 2
    print("PLAN_EVIDENCE=" + json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 1 if evidence["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
