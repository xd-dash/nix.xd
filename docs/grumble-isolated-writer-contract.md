# Grumble independent writer contract (proposal)

Status: design-only; no runtime qualification or migration performed.

## Ownership

- Grumble application source and Grml image contract belong in the separate public `xd-dash/grumble` repository.
- `nix.xd` provides host/provider/architecture adaptation and an independent Nix-Alpine writer.
- The existing `nix-xd-arm` store, CoreOS VM1/VM2, Fatline roots and matrix declarations remain untouched.
- Smoke is not part of Grumble's normal build or qualification path.

## Isolation requirements

The proposed `nix-xd-grumble-arm` scope uses a distinct named volume (proposed `nix-xd-grumble-arm-store`) mounted as its *own* `/nix`. The Nix database, store paths, profiles, gcroots, and temp build directories must all belong to that volume. No read-write bind mount of the existing Agni/CoreOS `/nix` is permitted.

Use one authoritative writer per volume. Nix's normal build locks operate within that store and are not a cross-store coordination mechanism. An independent scope must fail closed if its mounted volume differs from the declared volume, and must never silently initialize or reset a nonempty unrecognized store.

A chroot does not provide store separation when it binds the same `/nix`; prefer an independently provisioned Nix-Alpine runtime. Read-only peer closure access is a later, separately qualified optimization, not a prerequisite.

## Generic interface

Keep `make stage`, `make show`, `make check`, `make build`, `make run`, and `make qualify` unchanged. Select the writer through `PROVIDER`, `SCOPE`, and `ARCH`; select the application via `FLAKE` and `TARGET`. No Grumble-specific logic in the existing CoreOS shared-store matrix.

The Grumble flake should expose `#qualify` for static/preflight checks and distinct `#build`, `#inspect`, `#boot`, and `#measure` application outputs. Build and boot qualification must not be conflated.

## Gates before production use

1. Provision an empty, separate volume and confirm its identity and writable mount.
2. Confirm two independently running Nix-Alpine scopes have distinct Nix database and GC roots.
3. Concurrently build trivial independent derivations; prove both stores remain healthy.
4. GC one store; prove retained roots and outputs in the other store remain unaffected.
5. Stop/recreate the Grumble writer; verify store persistence and no Agni/CoreOS interruption.
6. Qualify `grml-live` prerequisites, user namespaces, subuid/subgid mappings and Debian tooling inside the ARM64 Nix-Alpine runtime.
7. Build the pinned Grml ISO and record full logs, ISO SHA256, and elapsed time.
8. Boot using ARM64 UEFI and QEMU, capturing kernel/systemd/login/network evidence.

The existing Grml experiment is at `xd-dash/huram-abi-master`, `automation:experiments/grml-arm64`, pinned to upstream grml-live commit `6d729f059769e4d5be18f47bceb9d9f9d0bd5111`. Preserve that revision and provenance when extracting it to Grumble.

Do not retire the Huram Blacksmith workflow until local Mac qualification has passed and its replacement is reproducible.
