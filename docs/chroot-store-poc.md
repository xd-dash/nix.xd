# Generic persistent chroot-store POC

Make is the control plane. These targets have no dependency on Fatline, Agni or
Grumble application controllers. The POC itself runs through a generic runtime
flake inside Nix-Alpine.

## Local runtime selection

From the nix.xd checkout/worktree, configure the existing ARM Podman builder once:

```bash
cp examples/runtime-arm64-podman.mk nix-xd.local.mk
```

`nix-xd.local.mk` is ignored by Git and loaded before Make's defaults. It selects
architecture, provider, machine, builder scope, checkout staging path and the
common log directory. Command-line assignments override it. Other machines may
supply a different file with `make NIX_XD_CONFIG=/path/to/runtime.mk ...`.
No shell function named after an application is required.

For the currently configured builder, which already has its volume and namespace
profiles applied:

```bash
make stage &&
make chroot-store-qualify CHROOT_NAME=grumble
```

The name `grumble` here is only the store alias; no Grml build is performed.

## Provisioning and qualification

`chroot-store-attach` provisions a persistent volume at `/stores/<name>` through a
managed builder Quadlet declaration. It rejects conflicting mounts and nonempty
unmarked volumes. It may restart the owner, so pause owner builds first and stage
source afterward. CoreOS VM runners are separate and are not restarted.

The normal store stays at `/nix`; the chroot has separate store files and metadata
under `/stores/<name>/nix`. `PROJECT_STORE` explicitly selects `local` or one of
these attached persistent roots. Chroot builds require sandboxing without fallback.

The gate checks namespace/mount prerequisites, warms the small fixture tool
closures, builds unique outputs concurrently in both stores, and checks metadata
in both directions. It then executes a named flake app in each store view and
reads that store's unique output through logical `/nix/store`. It verifies that
a rooted chroot fixture cannot be deleted; releasing only that root allows only
that fixture to be deleted. No authoritative-store GC or deletion is performed.
Failures retain evidence and roots. The success marker is
`CHROOT_STORE_POC_RESULT=passed`.

## Metadata selection inside an execution view

Nix 2.34's runtime helper remaps the logical store directory; it does not redirect
all metadata directories. Consequently an inner `--store local` can open the
normal database even when binaries execute against the diverted store view.
The project launcher propagates the actual selected store URI through
`NIX_REMOTE`, and the qualifier queries that URI explicitly. It separately checks
logical output readability and selected physical database identity. See
[Nix's runtime helper](https://github.com/NixOS/nix/blob/2.34.9/src/nix/run.cc).

This is separate Nix store/database ownership for trusted same-user projects,
not a hostile-tenant filesystem boundary. Read-only peer mounts and arbitrary
store adapters remain separate capabilities; this POC does not implement Grumble.

## Current trusted-builder namespace profile

The locally exercised profile uses proc unmasking, a builder-only SELinux labeling
exception, and a filtered seccomp policy permitting nested UTS naming. It adds no
SYS_ADMIN and does not enable privileged mode or change host SELinux. These are
builder capability settings, not application guest policy. The final successful
profile should be consolidated into declarative bootstrap after the complete
store POC passes, rather than making applications repeat provisioning steps.

Diagnostic targets remain `builder-chroot-diagnose` and the generic
`project-run PROJECT_APP=chroot-store-diagnose`. They print selected security
fields, never the complete OCI environment or credentials. Logs use the shared
`NIX_XD_LOG_DIR`; evidence lives under `/stores/<name>/.poc/`.
