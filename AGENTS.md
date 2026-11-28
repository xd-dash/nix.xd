# nix.xd — binding contributor and agent policy

**MANDATORY before code changes:** Read [docs/CANONICAL-ARCHITECTURE.md](docs/CANONICAL-ARCHITECTURE.md), then [docs/architecture-v20261115.md](docs/architecture-v20261115.md). The canonical document takes precedence for new work; older docs explain transitional state only. Do not treat an existing legacy caller as an approved design example.

For cross-repository qualification, merge or teardown also read Agni's `local/fatline/qualification/POST-QUALIFICATION-CLEANUP.md`. Legacy inventories may only shrink; tests must never require deleted adapters to reappear. Remove only resources created by the identified run.

## Nonnegotiable boundaries

- macOS may bootstrap Podman Machine and scoped host resources, but after bootstrap the **Nix-Alpine owner is the execution authority**. Host Make targets are thin selectors and transports.
- nix.xd implements generic rootless Podman/provider lifecycle, committed immutable staging, Nix store domains, grants, pinned flake execution, generic guest SSH transport and evidence. **No Agni/Fatline/Shoal/Farcaster/Probot placement, policy, service lifecycle or qualification acceptance logic.**
- Agni owns VM/Quadlet topology, activation, service ACLs and application admission. Smoke owns reusable Go composition, GHXD device auth, credentials/source generations and generic qualification tools. Application repositories own execution semantics.
- **DO NOT ADD:** `project-host-run` callers, host-actions, recurring host Podman application workflows, `PROVIDER=container` canonical fallback, application-specific nix.xd targets, or copied legacy Shoal helpers. `mk/legacy-host-actions.mk` and `mk/legacy-shoal.mk` are quarantined exceptions. Retire once callers are proven migrated.
- New user entrypoints must compose `make run FLAKE=... TARGET=...`, `make project-run` or `make guest-app`, with source locks and no business logic in Make.
- No moving branch HEAD execution. CalVer branch = workspace, **full SHA = runtime identity**; immutable committed checkout required.
- One Nix store writer; readonly readers. Secrets in explicitly granted runtime volumes, not `/nix/store`; rootless UID/SELinux access, no broad Podman socket or privileged shortcuts. State in `~/.local/state/nix-xd`; logs in `~/.local/nix.xd/logs`.
- GHXD native grants deliberately expand access to the trusted Nix-Alpine owner. Do not run old host writer concurrently. Do not mark migrated until mount/auth-refresh/source-sync/negative-case/teardown live evidence exists.
- Mac/CoreOS sandbox is disposable; avoid new failover, rolling migration, compatibility retention or production rollback engineering.
- **Static markers are not runtime pass evidence.** Preserve actual exit code, stderr/stdout, revision, cleanup and negative tests. Previous passing gate remains evidence only for unchanged scope.

## Required checks

Before and after changing execution authority, run `make architecture-check`. On the same pinned local checkouts run `make architecture-audit AGNI_DIR=/path/to/agni SMOKE_DIR=/path/to/smoke`, then `make check-static`. If the change affects mounts, credentials or guests, run the associated **live** gate on the target environment before saying it passed. Do not suppress failing checks or rewrite tests to force a PASS.

When a request contradicts this design, explain the conflict and implement the canonical path, not the outdated pattern. Update the normative document and its guard in the same change if the design itself deliberately changes.
