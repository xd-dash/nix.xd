# Declarative Nix-Alpine builder store profiles

The authoritative store and alternate chroot stores have different ownership and metadata.
This is **generic nix.xd infrastructure**, not a Fatline or Grml deployment feature.

## Store topology

| Declaration | Mount | Access | Owner |
| --- | --- | --- | --- |
| `STORE_VOLUME` | `/nix` | writable | Nix-Alpine owner |
| `BUILDER_CHROOT_STORES = alias=volume ...` | `/stores/alias` | writable | same Nix-Alpine owner, independent chroot Nix state |
| `PEER_STORES = alias=volume ...` | `/peer/alias` | read-only | another store owner |

A chroot Nix store has its own database and garbage collection roots, even though its
logical Nix paths are `/nix/store/...`. Flakes specify dependencies and app outputs;
they do **not** automatically remap store metadata. The selected project executor
must explicitly choose the chroot store context. Do not treat a read-only peer mount
as an independently usable Nix installation without an appropriate execution context.

## Profile declaration

Copy these entries to the Git-ignored `nix-xd.local.mk`, retaining the existing
`MACHINE`, `SCOPE`, `PROVIDER`, `WORKSPACES`, and `WORKLOAD_FLAKE`
selection:

```make
STORE_VOLUME = $(SCOPE)-store
BUILDER_CHROOT_STORES = grumble=$(SCOPE)-grumble-chroot
BUILDER_CHROOT_NAMESPACE = 1
BUILDER_CHROOT_SYSCALLS = 1
CHROOT_SELINUX = keep
```

Add further aliases to `BUILDER_CHROOT_STORES` when needed. Chroot volume names must
be unique and cannot equal the authoritative volume or a read-only peer volume.
The `keep` SELinux policy is the safe default: `disabled` may be selected only
when the existing controlled comparison establishes a need. The namespace and
syscall restrictions remain scoped to the builder container.

## Supported interfaces

```sh
make builder-store-profile-plan
make builder-store-profile-check
make bootstrap-builder-profile
```

`builder-store-profile-plan` validates configuration without touching Podman.
`builder-store-profile-check` runs the host-independent store-specific regression
suite (no VM, no Fatline tests). `bootstrap-builder-profile` preflights the
declaration, bootstraps the selected rootless Podman builder, stages the project,
and applies the selected chroot and security policy.

For an **already initialized** builder, use `make builder-store-profile-apply`.
Applying the profile may restart that builder to activate Quadlet drop-ins. It
does not intentionally restart other scopes or perform authoritative-store GC.
The existing profile remains opt-in; `make bootstrap` alone is unchanged.

On a dedicated test builder, `make builder-store-profile-qualify-idempotence`
checks that applying the same profile again keeps the current container identity.
This is not a replacement for the completed original chroot-store runtime POC.

## Evidence and boundaries

The accepted Mac ARM64 chroot POC reported:

```text
CHROOT_STORE_POC_RESULT=passed concurrent=true metadata=separate retention=separate view=chroot authoritative_gc=false
```

Its intentional negative assertions included invalid cross-store paths and protected
GC roots. This POC does not need to be repeated solely to establish the profile.
A future **fresh-instance integration** check can evaluate the profile bootstrap,
idempotence, and more than one named chroot without disturbing the established builder.

The profile currently orchestrates separate established runtime handlers. It is not
a transactionally applied pre-first-start Quadlet specification: initial setup can
restart the selected builder while adding mounts, unmasking the required `/proc`
paths, or applying the minimally extended seccomp policy. Atomic initial Quadlet
rendering would be a distinct follow-on feature, not a prerequisite to accepting
the demonstrated store-isolation behavior.

The broad `make check-static` suite includes Fatline application/VM regressions.
A failure in that unrelated suite does not override the independently qualified
chroot-store POC; use `make builder-store-profile-check` for the store-specific
static boundary and retain the broad gate for integration.

## One-shot fresh ARM qualification

On the existing selected, running Podman Machine, use:

```sh
make builder-store-profile-qualify-fresh
```

This creates only the separate `nix-xd-arm-chroot-qualify` builder, with image
`localhost/nix-xd:arm64-chroot-qualify`, its authoritative volume, and
two writable volumes (`grumble` and `experiments`). The gate runs the
store-specific static suite, validates the profile, rejects any preexisting
qualification resources, bootstraps and stages the builder, checks all three
mounts and non-root/seccomp constraints, reapplies the profile, then checks
that the container ID is unchanged. The entire gate is wrapped in a single
timestamped `*-builder-store-profile-qualify-fresh-*.log`. Failed runs
retain partial resources for diagnosis; successful ones retain the builder
for further qualifications. Do not rerun a completed gate without explicitly
cleaning only its qualification resources.

It requires an already-running Podman Machine and does not create or resize
the VM. The default local Make configuration selects the machine/workspaces;
the qualification forces its own scope, image, volume names and secure policy.
This gate does not re-run the accepted chroot-store POC or perform store GC.

## Inventory and selective cleanup

```sh
make builder-runtime-inventory
```

This reports all containers, images, volumes, and Nix-related user services
on the selected Podman Machine without changing anything. A stopped container
or an old image is not automatically stale: check attached volumes, Quadlet
services and CoreOS guest consumers before removal. Never use an indiscriminate
`podman system prune --volumes` on a machine carrying retained stores.

Only the **dedicated qualification scope** may be reset using:

```sh
make builder-store-profile-qualify-clean \
  QUALIFY_RESET_CONFIRM=ERASE:nix-xd-arm-chroot-qualify
```

Cleanup checks no other container uses its three named volumes, stops its
Quadlet, removes only its scope-specific container, three volumes and
qualification image tag, and preserves unrelated builders and CoreOS
resources. Cleanup is destructive **only for that qualification scope**;
it deletes its store roots and outputs, so retain the qualification log first.
If you used a different `QUALIFY_STORE_SCOPE`, match the confirmation
string to that exact name. The cleanup interface refuses to act without
the confirmation. A fresh qualification can then be run again.

For arbitrary legacy containers/images, use the inventory to select exact
resource IDs. Do not automatically delete any volume that might contain an
authoritative Nix store or a CoreOS-mounted closure.

## Separate authoritative writer alternative

The consolidated branch also carries the earlier Grumble independent-writer
proposal and the read-only `make store-isolation-check` contract. That gate
compares distinct Nix-Alpine scopes, each with its own authoritative `/nix`
volume. It does **not** claim the same properties as the chroot-store POC,
and it is not a prerequisite to using the qualified same-container model.
The original checker assumes the default `<scope>-store` volume naming;
custom volume selections require an explicit future extension.

Use `make store-isolation-static` for the self-contained mock contract.
The historical `codex/grumble-isolated-writer` branch remains available
for provenance; the consolidated branch preserves its implementation,
with the CI workflow renamed to generic Nix store isolation.

## Workspace and image cleanup review

`make workspace-inventory` reports linked Git worktrees, stale
worktree *metadata* via `git worktree prune --dry-run --verbose`,
and nearby potential checkout directories. These are candidates,
not proven stale workspaces. Use `git worktree remove <exact-path>`
only for an intentionally retired, clean worktree. Do not remove an
active branch checkout or run `rm -rf` over the workspace directory.

`make builder-runtime-inventory` lists Podman images, containers, volumes
and managed services in the selected machine. An image can be deleted
by exact name only after checking it is not used by running or stopped
containers, or selected in a Quadlet. Retain named Nix volumes until
their ownership, roots, and consumers have been reconciled.
Avoid volume pruning and whole-machine pruning.

## Consolidated development branch

Use `codex/nix-store-consolidated` for the ongoing integration. It includes
the retained independent-writer inspection contract and the existing
multiple-chroot-store infrastructure. The old branches are kept as historical
references; do not reset an active local worktree merely to switch branches.

For routine cleanup on the selected Podman Machine, after reviewing
`make builder-runtime-inventory`, the explicit
`make builder-image-prune-dangling DANGLING_PRUNE_CONFIRM=YES` target
runs `podman image prune --force`, which removes dangling images
but not tagged images or named volumes. This is narrower than
`podman image prune -a` and is not equivalent to system pruning.

Inspect stale Git worktree metadata with `make workspace-inventory`.
`git worktree prune --dry-run` in that report does not delete anything.
To remove a workspace, select an exact path and run `git worktree remove`
only after ensuring it has no uncommitted changes and is not serving active
qualification or application source. Delete obsolete worktree metadata only
after its linked checkout is no longer needed.

## Interrupted first bootstrap: resuming the scoped qualifier

A Podman Quadlet restart recreates the container writable layer, including
the staged `/workspaces/<checkout>` tree. This was discovered when the first
fresh qualification successfully bootstrapped and mounted both chroots, but
the namespace restart removed the staged flake before `#builderPolicy` was built.

`bootstrap-builder-profile` now stages after mounting and namespace changes,
then applies the syscall policy, then stages again after any seccomp restart.
This preserves the final flake for application execution.

The dedicated qualifier can recover without touching the store volumes:

```sh
make builder-store-profile-qualify-resume MACHINE=coreos-arm64
```

The resume gate requires the expected qualification Podman container, Quadlet,
image tag, authoritative volume, and two correctly mounted chroot volumes
to already exist. It does **not** run bootstrap, delete volumes, or reset GC
roots. It finishes the staged-policy sequence, verifies security and mounts,
and checks idempotence. It logs the result under the resume target name.
This does not qualify full atomic initial Quadlet generation; post-bootstrap
restarts remain part of the current profile design.
