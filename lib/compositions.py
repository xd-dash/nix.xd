#!/usr/bin/env python3
"""Validate flake-declared store ownership and workload placement."""
import argparse
import json
import re
from pathlib import Path

NAME = re.compile(r'[a-z][a-z0-9-]{0,39}\Z')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(plan):
    require(plan.get('version') == 1 and NAME.fullmatch(plan.get('name', '')), 'Invalid composition identity')
    require(plan.get('system') in ('aarch64-linux', 'x86_64-linux'), 'Unsupported composition system')
    placements, domains, workloads = (plan.get(k, {}) for k in ('placements', 'domains', 'workloads'))
    require(placements and domains and workloads, 'Empty composition')
    ports, containers = set(), set()
    for name, placement in placements.items():
        require(NAME.fullmatch(name) and placement.get('kind') in ('host', 'coreos'), 'Invalid placement')
        require(placement.get('transport') == ('bind' if placement['kind'] == 'host' else '9p'), 'Invalid store transport')
        if placement['kind'] == 'coreos':
            port, container = placement.get('sshPort'), placement.get('container', '')
            require(type(port) is int and 1024 <= port <= 65535 and port not in ports, 'Conflicting SSH ports')
            require(NAME.fullmatch(container) and container not in containers, 'Conflicting VM identities')
            ports.add(port)
            containers.add(container)
    for name, domain in domains.items():
        require(NAME.fullmatch(name), 'Invalid domain name')
        owner = domain.get('owner', {})
        require(isinstance(owner, dict) and owner.get('placement') in placements, 'Domain needs exactly one owner placement')
        require(type(owner.get('scopeStore')) is bool, 'Missing backing-store policy')
        readers = domain.get('readers', [])
        require(readers and len(readers) == len(set(readers)) and all(p in placements for p in readers), 'Invalid domain readers')
        require(domain.get('provisioning') in ('existing-host-store', 'deferred'), 'Unknown provisioning policy')
        if domain['provisioning'] == 'existing-host-store':
            require(placements[owner['placement']]['kind'] == 'host' and owner['scopeStore'], 'Existing common store must remain host-owned')
    for name, workload in workloads.items():
        require(NAME.fullmatch(name), 'Invalid workload identity')
        require(workload.get('placement') in placements and workload.get('domain') in domains, 'Unknown workload binding')
        require(workload.get('access') == 'read-only', 'Consumers cannot write the shared store')
        require(workload['placement'] in domains[workload['domain']]['readers'], 'Workload placement cannot read this domain')
    return plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(Path(args.input).read_text())), sort_keys=True))


if __name__ == '__main__':
    main()
