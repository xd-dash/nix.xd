# Canonical execution architecture (2026-11-16)

Status: normative **target design**, not proof that the migration is complete. This document supersedes older idiom examples for new development. Existing compatibility adapters remain quarantined until replacement passes live qualification.

## Read first / decision rule

For every new action, answer: **Who owns the policy? Who merely transports it?** Put policy in its owner repository. Do not duplicate it in nix.xd. If a proposed change contradicts this contract, reject the change rather than mimic a working legacy caller. If uncertain, stop and trace the current source lock, entrypoint and execution authority. Do not infer that a historical passing gate authorizes a different one.

## Authority boundaries

| Layer | Owns | Must not own |
| --- | --- | --- |
| macOS | One-time Podman Machine/bootstrap, explicit host resource grants, scoped teardown | Recurring GHXD, Probot, Quadlet, VM/service composition |
| nix.xd/Nix-Alpine | Generic provider adapter, immutable staging, Nix store domains, read/write grants, pinned flake launch, SSH guest transport, generic evidence | Fatline/Shoal/Probot application state machines, source authorization, guest service policy |
| Agni | VM identity, topology, CoreOS boot config, systemd/Quadlets, ACLs, guest plans, activation and acceptance gates | GHXD internals or generic host transport implementation |
| Smoke | Go tool composition, GitHub device authorization, SOPS+age credential operations, SHA-addressed source generations, reusable qualifiers | Agni placement/topology or privileged macOS lifecycle |
| Application | Webhooks, handlers, domain idempotency, integration tests, effects | Shared infrastructure/admission interface |

The canonical chain is: **Mac Make -> nix.xd provider -> Nix-Alpine pinned flake -> Agni plan / Smoke executable -> generic guest transport -> CoreOS systemd/Podman**. The host is an operator/bootstrap boundary, not a persistent application control plane. A Make target selects an application-owned flake, it does not implement an application state machine.

## Interfaces and immutability

- Prefer `make stage CHECKOUT=...` for temporary committed source import while GHXD migrates, `make run FLAKE=... TARGET='#app' ARGS=...` for generic Nix execution, `make project-run PROJECT_FLAKE=... RUNTIME_FLAKE=...` for generic project launcher, and `make guest-app FLAKE=... TARGET='#package' GUEST_APP_REV=<40-hex-SHA>` for generic SSH stream.
- Agni selects `make -C local/fatline qualification QUALIFICATION=<gate>`. These names are application policy; never duplicate them as nix.xd targets.
- CalVer branches are mutable *development workspaces*, not runtime identity. Qualification pins **full 40-character source commit SHAs**. Lock updates create a new candidate with affected checks rerun.
- Staged source must be committed and verified to the revision, with a stable runtime binding (VM instance/boot identity and guest host-key) for topology claims. A static plan is not runtime identity proof.

## Storage and security

- One writer per Nix store domain; immutable/read-only sharing to consumer containers or VMs. VM-local stores and persistent guest state have separate owners.
- Mounts are explicit named Podman volumes or 9P grants, using user namespaces, mapped UID/GID, SELinux and least authority. No broad Podman socket or privileged owner as a shortcut.
- Secret state is runtime-only in dedicated credential volumes, **never** in `/nix/store`, derivation inputs/outputs, checked-in configuration, process args or logs.
- Existing native GHXD grants deliberately give the Nix-Alpine owner writable secret access; this is broader than the old isolated sidecar. Treat it as an explicit, **unqualified security decision**, not an innocuous rename. The old operator and new credential writer must never run simultaneously.
- Persistent host state: `~/.local/state/nix-xd/`; evidence/logs: `~/.local/nix.xd/logs/`, per invocation. Worktree-local `.state` is not a persistent-control-plane default.

## Forbidden new idioms (deny by default)

1. No new `project-host-run`, `local/*/host-actions/*`, macOS application Podman creation, or `PROVIDER=container` fallback for canonical runs.
2. No new Shoal/Fatline/Farcaster/Probot-specific nix.xd targets, scripts, provider switches, service ACLs or activation.
3. No moving branch/tag evaluation at runtime, uncontrolled `git pull` or implicit workspace selection; pinned SHA and clean source are required.
4. No checkout-local persistent state, host-mutable secrets in Nix outputs, permissive mounts, privileged containers or silent grants.
5. No parallel Bash/Python reimplementation of Smoke Go business behavior, nor direct Agni implementation of generic transport.
6. No conflating structural/static checks with observed live execution; do not print PASS after skipped or partial execution.
7. No production failover, rolling migration, retention or backwards compatibility complexity for the destroyable macOS qualification sandbox without an explicit new requirement.
8. No new compatibility alias introduced to preserve an obsolete route. Identify callers and migrate them to one canonical interface.

## Transition inventory and cutover rules

- `mk/legacy-host-actions.mk`, `bin/nix-xd-project-host-run`, `mk/legacy-shoal.mk`, and host Git archive staging are **known outstanding exceptions**. Their presence is not permission to add callers.
- Source sync switches only after an independently observed native GHXD qualification: rootless mounts and one-writer denial, SOPS+age read and bounded refresh, wrong SHA/manifest refusal, correct source generation, no concurrent host writer, no secret in logs/store, and clean scoped teardown. Do not remove the old adapter sooner.
- Agni Fatline factory-live and supervised systemd SIGKILL/restart/reclaim/idempotent-effect tests are separate. No production promotion from static results.
- After migration passes, delete obsolete adapters and update static checks to assert their **absence**; never leave checks that force legacy files to persist indefinitely.

## Qualification contract

Every gate names its owner, selected source SHAs, prerequisites, side effects, cleanup scope, negative case, machine-readable success/failure marker, raw stdout/stderr and exit status. Test on the chosen runtime, not via asserted marker strings. Retain earlier passing evidence only when the interface and acceptance scope are unchanged. Stop on first failing gate and fix the owning repository. Mac resources are disposable, but unrelated running services must remain unchanged.

## Commands (do not imply a pass)

```sh
make architecture-check
make architecture-audit AGNI_DIR=/path/to/agni SMOKE_DIR=/path/to/smoke
make check-static
```

For canonical Fatline qualification and native GHXD gate details, read Agni `local/fatline/qualification/architecture-v20261115.md` and the candidate-specific source lock. Never invent a new qualified revision by substituting the branch HEAD.
