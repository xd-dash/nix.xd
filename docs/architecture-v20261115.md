# nix.xd execution authority — v20261115

Status: **target contract / migration baseline**, not a claim that all historical
callers already comply. This branch is a zero-version CalVer candidate: no
backwards compatibility is promised after its qualifications pass.

## Ownership

- **macOS host**: one-time provisioning of Podman Machine, executable runtime,
  narrowly scoped mounts, and communication credentials; explicit uninstallation.
  No recurring application service construction from macOS.
- **nix.xd**: provider adapter, owner container lifecycle, immutable checkout
  staging, Nix store/domain grants, generic flake execution, guest SSH transport,
  generic evidence and teardown. No Fatline, Probot, Shoal, Farcaster or
  application topology in the *canonical* API.
- **Agni**: CoreOS topology, VM/Quadlet/service composition, systemd ownership,
  guest plans, application mounts, activation guards and acceptance decisions.
- **Smoke**: Go tool composition, GHXD credential and source operations,
  reusable executable qualification primitives, exact SHA evidence.
- **Application**: application behavior, library dependencies, integration and
  effect semantics.

An operation's owner is the repository that defines its policy and pass/fail
contract, not the repository that provides its process transport.

## Canonical operator path

`macOS Make -> nix.xd generic provider/transport -> Nix-Alpine pinned flake
-> Smoke executable / Agni composition -> guest transport -> CoreOS`.

After bootstrap, use `make stage` solely to import a **committed immutable
checkout** from the host; `make run FLAKE=... TARGET=#...` for Linux Nix
applications; `make guest-app` for immutable package `guest.sh`; and
`make project-run` when a project supplies a generic Nix runtime launcher.
`run` must not silently rewrite `ARGS`, perform source sync, or assume an
application-specific provider.

`guest-app` is a generic SSH stream from the staged Nix artifact. It does not
own CoreOS status checks or know application role names. The guest accepts only
the exact project revision and caller-provided arguments. Agni constructs
credentials and application guards in its own candidate, never in the Nix store.

## Explicit transitional exceptions (not canonical)

1. `bin/nix-xd-task stage` still archives committed host Git and copies it
   through Podman. This is a read-only source-import boundary, **not**
   in-container source acquisition. Retain it until Smoke GHXD can seed every
   selected source and Agni can dispatch from an immutable Nix-Alpine generation.
2. `bin/nix-xd-project-host-run` executes a checked-out project's
   `local/<application>/host-actions/<action>.sh` on macOS. It currently
   serves Smoke GHXD, whose `local/ghxd/host-operator.sh` manipulates Podman
   containers and dedicated volumes. This is a **known architecture exception**,
   not a precedent for new application actions. Do not introduce new callers.
3. Historical Shoal, migration, rollback, failover, Apple Container and
   rebootstrap targets still exist for prior evidence. Do not select them for
   the canonical Fatline qualification, and do not copy their patterns.
   Retire only after checking repository and script callers.

## Filesystems and credentials

- One authorized writer per Nix store domain. Read-only Nix store mounts for
  guest readers; VM-local writable state belongs to VM-local volumes.
- User namespaces, UID/GID and SELinux grants are enforced by provider/OS
  primitives; never use a blanket privileged container.
- Application and credential state belong to named Podman volumes/9P grants;
  store paths are immutable artifacts, never a secret store.
- No private key, GitHub token or ephemeral credential is stored in Nix
  derivation inputs/outputs, build logs, or git.
- Persistent host-owned paths: `~/.local/state/nix-xd/`; logs:
  `~/.local/nix.xd/logs/`. Application evidence is grouped per invocation.
- Sandbox teardown is a first-class operation. No production-oriented
  failover, migration rollback or generation retention requirement for a
  destroyable macOS qualification environment.

## Qualification discipline

Source-locked revision -> static contract -> build -> isolated live process
-> native guest generator/systemd -> activation decision.

Each gate MUST have an exact source pin, one named result marker, a meaningful
negative test, side-effect scope, and cleanup/result evidence. Structural
validation supersedes grepping incidental JSON/key formatting or duplicated
code text. Errors must retain stdout **and** stderr. A marker is not a passed
gate unless the operation ran and its exit code is zero.

A previously passed gate is not rerun unless its interface/fixture or accepted
goal changed. Stop at a failing gate, fix its owner, and preserve earlier
evidence.

## Migration and removal procedure

The architecture cutover requires **both** an audit of all
`project-host-run`/host-action callers and a live Nix-Alpine-only GHXD
source-sync, credential-mount and CoreOS guest transport qualification.
Then remove host-side GHXD volume lifecycle orchestration from the canonical
path; only then delete compatibility targets and application-specific nix.xd
files. An untested host-side replacement is *not* a completed cleanup.

Before changes touching this contract, run `make architecture-check` and
the repository's normal static checks. This is a repository ownership
guard, not the runtime qualification.

## Native GHXD grant candidate (opt-in; not yet live-qualified)

`examples/ghxd-native-grants.json` declares three explicit named volumes
for the Nix-Alpine owner: GHXD secret, home and source generations. The
existing `lib/runtime_grants.py` validates grant ownership and the
rootless bootstrap renders mounts. **The previously started owner does not
inherit new grants**. Apply this manifest only during an explicit disposable
owner bootstrap; prove read/write access and one-writer isolation with the
generic `grants-plan` / `grants-execute` checks before dispatch.

Smoke `v20261115` now includes an opt-in `#ghxd-native` app that can operate
on those pregranted volumes and stage source generations directly inside the
Nix-Alpine owner. It does not require a host Podman launcher for each GHXD
run. This code is an unqualified candidate, *not* authorization to delete the
current host operator or credentials. Giving the trusted Nix-Alpine owner
writable GHXD secret access expands its authority compared with a dedicated
secret-isolated sibling container. Select this model only if that explicit
trust boundary is acceptable. Never supply a broad Podman socket.

The migration gate must verify the initial grants, SOPS+age access, refresh,
source generation, absence of concurrent old host adapters and isolated
teardown with the candidate running on an intentionally disposable owner.
If it fails, keep the old GHXD path selected until its replacement passes.
