# Persistent chroot-capable builder profile

The generic declaration is BUILDER_CHROOT_STORES: a whitespace-separated list of
`name=volume` pairs. STORE_VOLUME selects the ordinary `/nix` volume. PEER_STORES
selects optional existing read-only peer volumes. All three are bootstrap inputs;
Agni and Grumble remain independently owned project flakes.

Declare them in the untracked nix-xd.local.mk or pass them to Make. For example:

```make
include examples/runtime-arm64-podman.mk
STORE_VOLUME = nix-xd-arm-store
BUILDER_CHROOT_STORES = grumble=nix-xd-grumble-store
CHROOT_SELINUX = disabled
```

The identity `grumble` selects a generic store slot. It does not install Grumble,
build a Grml image, or embed project orchestration in Nix-Alpine.

## First start

`make bootstrap-profile` validates the complete declaration, bootstraps the
Podman Machine if needed, prepares persistent volumes and their ownership,
derives a restricted seccomp policy, and writes one rootless Quadlet before
starting the builder. It stages the committed runtime source, verifies declared
mounts, and checks private proc and UTS namespaces as the ordinary builder user.
It never switches the builder's global `/nix` mount.

The seccomp policy retains the machine's restrictive default and adds the two
UTS calls required by nested Nix sandboxes. The profile explicitly unmasks proc
paths for the trusted builder. CHROOT_SELINUX defaults to keep; disabled explicitly
adds SecurityLabelDisable=true to this builder's initial Quadlet. It does not
change the machine's SELinux enforcement or other containers. The profile does
not use privileged mode or an unconfined seccomp profile. This is a capability
profile for trusted build workloads, not a hostile-tenant isolation boundary.

The readiness tools are flake outputs retained under
`/nix/var/nix/gcroots/nix-xd/bootstrap-profile/tools`. Readiness verifies the
namespace operations instead of inferring support from volume allocation.
The primary and alternate volumes are persistent; restarting or recreating the
builder does not intentionally erase them. Existing differing Quadlets are
rejected instead of being patched or restarting an active builder in place.

Use `make bootstrap-profile-check` for focused host-side checks.
Use `make bootstrap-profile-local` for one logged run of those checks, first-start
bootstrap, readiness and the generic isolated-store qualification.

```sh
make bootstrap-profile-local \
  BUILDER_CHROOT_STORES="grumble=nix-xd-grumble-store" CHROOT_SELINUX=disabled
```

For each declared alternate store, qualification reuses the bounded runtime POC:
concurrent primary/alternate builds, separate databases, execution in each
selected view, protected roots and release of only the fixture's own root.
Bootstrap rejects volumes already attached writable to another container while
allowing explicitly mounted read-only consumers to remain attached.
It does not collect garbage in the primary store or run application tests.
Fixture evidence stays in each alternate store's `.poc/` directory. Console
evidence uses the normal shared log override or repository-local `.logs/`.
Run `make bootstrap-profile-qualify` to repeat only that store qualification.

This first-start adapter is currently available for ARM64 macOS with Podman.
The first ARM run installed and staged successfully, but its private proc check
failed with permission denied while retaining SELinux labeling. The subsequent
read-only comparison isolated SELinux: baseline=1, label_disabled=0, owner unchanged.
Full qualification with the explicit disabled setting remains pending.
Run `make bootstrap-profile-compare` to compare
two temporary, read-only-store probes differing only in their SELinux labeling.
The comparison reuses the built readiness tools and restricted seccomp policy,
checks that the owner remained running with the same ID, and never rewrites its
Quadlet or changes its label. Each namespace probe has a 20-second timeout.
The comparison does not automatically change the running builder's configuration.
To replace the failed first-start builder using the corrected declaration, run:

```sh
make bootstrap-profile-recreate \
  BUILDER_CHROOT_STORES="grumble=nix-xd-grumble-store" CHROOT_SELINUX=disabled
```

This explicitly stops the selected managed builder, removes its container and
generated Quadlet, then performs first-start bootstrap, readiness and isolated-store
qualification. It retains every named volume and its contents, including roots
and built tools, and leaves the Podman Machine and other containers unchanged.
It does not rewrite a running builder or copy stores. The full operation is logged.

Declarations, packaged readiness tools and store selection support both Linux
architectures; native AMD64 first-start provisioning still needs its adapter and
runtime qualification. There is no emulated AMD64 gate in this change.

## Project execution

Once bootstrap is ready, projects choose their own app, dependencies, retained
outputs and runtime policy through the same launcher:

```sh
make project-run PROJECT_FLAKE=<agni-flake-reference> PROJECT_APP=<app> \
  PROJECT_STORE=local
make project-run PROJECT_FLAKE=<grumble-flake-reference> PROJECT_APP=<app> \
  PROJECT_STORE=/stores/grumble
```

References must be pinned or refer to separately staged project sources as
appropriate for the project. The launcher passes the selected store explicitly
and exports it for subsequent Nix operations; chroot execution uses the store's
private filesystem view. No global mount change is shared between invocations.
Calls to different stores can run concurrently. Flakes must preserve that
selection when invoking their own Nix subprocesses.

The earlier apply/complete/diagnose targets remain legacy maintenance interfaces.
Neither bootstrap-profile nor its local gate uses those retrofit paths. Fresh
development should use the first-start declaration above, without INITIAL_PROFILE
flags, isolated qualification builders, migration steps or application controllers.
