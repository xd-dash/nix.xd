#!/usr/bin/env python3
"""Derive a restricted builder policy from the machine's configured default."""
import json
import sys

UTS = {"sethostname", "setdomainname"}


def render(profile):
    if not isinstance(profile, dict) or profile.get("defaultAction") != "SCMP_ACT_ERRNO":
        raise ValueError("Expected restrictive Podman default seccomp policy")
    syscalls = profile.get("syscalls")
    if not isinstance(syscalls, list):
        raise ValueError("Missing seccomp syscall list")
    # Remove conditional entries covering the UTS calls, then grant them explicitly.
    # Keep all other default rules, architecture and errno settings intact.
    filtered = []
    for rule in syscalls:
        names = rule.get("names")
        if not isinstance(names, list):
            raise ValueError("Invalid syscall rule")
        kept = [name for name in names if name not in UTS]
        if kept:
            filtered.append({**rule, "names": kept})
    filtered.append({"names": sorted(UTS), "action": "SCMP_ACT_ALLOW"})
    return {**profile, "syscalls": filtered}


def main():
    try:
        result = render(json.load(sys.stdin))
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        print()
    except (ValueError, KeyError, TypeError) as exc:
        print("Builder policy rejected: " + str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
