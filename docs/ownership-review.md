# Runtime and composition ownership review

Reviewed 2026-11-11 against nix.xd's ARM qualification branch through 2e375b4.
This review does not claim that the extraction below is already implemented.
Grumble is outside the implementation scope of this review.

## Intended dependency direction

Agni and Grumble own project flakes. Those flakes run through Nix-Alpine and
compose generic capabilities supplied by its pinned runtime dependencies.
nix.xd selects the architecture, provider, builder and project flake, then launches
that flake through Nix-Alpine. Application controllers must not depend on being
installed into nix.xd's source tree. Smoke/Wisp owns reusable execution,
credentials, SSH and systemd runtime primitives.

| Responsibility | Destination |
| --- | --- |
| Builder installation, architecture/provider selection, thin Make launcher | nix.xd |
| Generic Linux execution environment, Nix, store/mount capabilities and reusable runtime package | Nix-Alpine |
| CoreOS provisioning and Fatline/Farcaster/Starwisp/Astrochicken composition, startup/recovery and qualification policy | Agni flakes |
| Grml build/provision/qualification policy | Grumble flakes |
| Transport, credential operations and reusable systemd execution | Smoke/Wisp |

A generic Python dependency can be packaged reproducibly and exposed through
Nix-Alpine. It must not dispatch application names or import application modules.
Its consumers choose the operations and interpret application success. Don't
add a second Python SSH/systemd implementation alongside Smoke/Wisp.

## Findings in nix.xd

| Finding | Evidence | Disposition |
| --- | --- | --- |
| Fatline application orchestration remains installed in the generic launcher | `lib/fatline_*.py`, Makefile's `fatline-*` sequences and tests | Move controllers, policy, declarations and tests together into Agni; keep reliability coverage |
| Generic flake owns application declarations and pins | `flake.nix` exports `fatlinePlans`; `compositions/fatline-coreos.nix` selects Agni/application revisions | Agni must resolve these inputs in its own flake; nix.xd selects that project flake |
| The composition runtime is a fixture-specific controller | `Runtime` accepts only `shared-store-matrix`; `resolve` requires six exact reader names and a common host store | Extract transport/state primitives; do not ship this entire controller as a generic library |
| Application benchmark is embedded in the composition runtime | `application()` in `lib/compose_runtime.py`, `applicationRedis` output and `qualifiers/redis-application.sh` | Move the benchmark to its owning composition or an explicit qualification fixture |
| Placement schema assumes CoreOS and 9P | `lib/compositions.py` binds placement kinds to bind/9p; execution selects Starwisp paths | Split generic capability validation from Agni's current placement adapter; keep unsupported transports rejected |
| Some useful primitives are bundled into policy modules | `run`, `write_json`, subprocess timeouts and lock use | Extract small runtime APIs with their own tests rather than importing a composition controller |
| State, source and executable paths share one checkout root | Module-level `REPO`, `.state` paths and calls into `REPO/bin` | Introduce explicit runtime tools and durable state locations before relocating controllers |
| Host controllers depend on ambient Python | Makefile `PYTHON` and host-side controller invocations | Package controller dependencies in the project flake; isolate any truly host-required transport helper behind an explicit interface |
| Stage/run is already a generic starting point | `bin/nix-xd-task` stages committed source and invokes selected flake outputs in the builder | Extend this path rather than growing more application targets; structured arguments must replace fragile string splitting when needed |
| Builder volumes and peer mounts have useful generic contracts | `lib/builder-stores.sh` validates volume/alias names, writable-store exclusion and missing peers | Retain these invariants and qualify any new store adapter independently |
| ARM and x86 share output interfaces but still bootstrap differently | `flake.nix` selects the pinned nix-alpine source for x86 and local `arm` context for ARM | Preserve bootstrap differences; keep project flake contracts architecture-neutral after bootstrap; no x86 qualification is implied |

Generic infrastructure qualification may remain with the generic runtime: missing
peer rejection, read-only mounts, root retention, subprocess failures, locking and
atomic state. Specific Fatline readiness, bootstrap denial, Redis crash recovery,
Skymill behaviour and VM2 non-interference belong to Agni's qualification flake.
The six-reader topology can remain a named infrastructure fixture, rather than a
restriction of the runtime API. Fixtures should not be prerequisites for every
project invocation.

## Store contract, including future chroot stores

Keep store identity separate from project identity. One project may use more than
one explicitly selected store, and a builder may execute independent project
flakes without giving either project write authority over a peer store.

Future resolved inputs need these distinctions, whatever their final field names:

* Store identity and owning builder, with exactly one declared writer.
* Backing volume or physical filesystem root, separately from the logical store
  directory embedded in closures. Current outputs use `/nix/store`.
* Store connection/URI selected explicitly for Nix operations, rather than a
  hidden process-wide default leaking between concurrent project runs.
* Selected read-only peer mount destinations; a peer mount is storage access,
  not an implicit merger of databases, closures or root registries.
* Execution mode: the builder's normal store or a specifically qualified isolated
  root/chroot adapter that presents the closure's expected logical paths.
* Per-store roots and lifecycle ownership, plus state/locks scoped to the affected
  deployment or store operation. Independent stores must not inherit a global
  application lock merely because one builder executes both projects.

`/peer/<name>` does not by itself make binaries referencing `/nix/store` execute
against that peer. The execution adapter must provide the required view, or the
workflow must explicitly copy/import a closure into its selected store. Do not
silently rewrite paths or mount a second writable database over the first.

The current workload validator and generated scripts assume `/nix/store`; they
are not a qualified arbitrary-store/chroot executor. Preserve the working
separate-volume builders and read-only peer capability. Do not introduce overlay
stores as an implicit requirement for project flake composition. Chroot and
peer execution remain explicit future adapters, not claimed functionality.

## Extraction order

1. Define a small generic runtime package: process results/timeouts, atomic state,
   scoped locking, logging and the existing build/root/mount mechanisms. Package
   it reproducibly for consumption through Nix-Alpine. Keep application state
   schemas and semantic success checks out of this package.
2. Make state root, runtime-tool locations, project source and store selection
   explicit. Preserve the existing absolute generation references and canonical
   lock locations. Do not copy deployment state or change credential ownership.
3. Move Fatline controllers, resolved declarations, Make sequences and application
   tests into Agni's flake. Invoke them through generic nix.xd -> Nix-Alpine ->
   project-flake execution. Host socket/transport operations must be an explicit
   Smoke/Wisp host capability, not an assumption that Linux can bind Mac sockets.
4. Keep short-lived compatibility delegates only where needed for existing local
   evidence. They may forward to an exact project flake, but must not contain a
   second implementation or continue selecting service policy.
5. Run the existing application gates against the extracted entrypoint: readiness,
   ACLs, host delivery, bootstrap failure/recovery, then autonomous CoreOS reboot.
   Retain the original evidence; migration does not make pending gates passed.
6. Add further store/execution adapters only when needed. Reuse the same project
   declarations on ARM/x86 and later GCP. Parent-runner supervision and spot
   replacement remain separate from guest application recovery.

This is an ownership refactor, not a reason to remove tests or rebootstrap the
working builder/VMs. Existing stores, roots, credentials, active bindings and the
single configured log directory must survive it unchanged.
