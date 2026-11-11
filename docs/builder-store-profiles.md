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
