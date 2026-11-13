# Starwisp shared Nix-store runtime contract

## Qualified baseline (2026-11-08)

Successful test: `20261108T204449Z-30616`.
Evidence location on the Mac workspace:
`.state/coreos-9p-fixed/starwisp/qualifications/20261108T204449Z-30616`.

The successful run reported:
- `PASS: NIX_9P_GUEST_MOUNT` (`ro`, `9p`, `trans=virtio`)
- `PASS: NIX_9P_OCI_ARCHIVE_READONLY` (readable gzip header only)
- `PASS: NIX_9P_NESTED_EXECUTABLE` (static BusyBox)
- `PASS: NIX_9P_NESTED_PODMAN_READONLY`
- `QUALIFY_STARWISP_RESULT status=passed exit=0`

This evidence is **retained locally**. Its manifest, guest logs, runner image digest,
disk and Ignition hashes should be treated as the baseline. The repository does
not claim to contain an uploaded copy of that qualification directory.
Never modify or overwrite the successful run directory in subsequent tests.
The currently running runner script archives prior failed overlays; it is not a
mechanism for moving the successful qualification evidence into source control.

## Execution boundary

1. Nix-Alpine owns the only writable `/nix` store, held in Podman volume
   `nix-xd-arm-store`.
2. QEMU exports that volume read-only with the built-in VirtIO 9P device.
3. CoreOS mounts it at `/var/mnt/nixstore`, read-only.
4. Rootless Podman receives a **guest-local disposable rootfs skeleton**, not a
   read/write filesystem based on the 9P mount.
5. A read-only bind mount maps the shared store into the container at
   `/nix/store`; executable absolute Nix store references resolve directly.
6. `bin/nix-xd-guest-store-exec` is the reusable guest-side runner. It verifies
   rootless Podman and the read-only 9P mount, creates an ephemeral rootfs and
   launches an executable under Podman. The host qualifier streams this helper
   over SSH without writing a persistent guest program.
7. No Nix store copying, OCI image import, or `--rootfs:O` on 9P is permitted.
   Runtime storage lives in CoreOS's existing rootless Podman storage.

Only the static BusyBox path has passed the end-to-end guest execution test.
The `storeProbeDynamic` GNU hello output is a new, optional dynamic-closure
qualification and remains **unqualified until a new guest run succeeds**.

### Reproduce the optional dynamic closure gate

Build on the already-running ARM Nix-Alpine (the output is a directory path):

```sh
export COREOS_GUEST_DYNAMIC_EXECUTABLE="$(
  podman --connection coreos-arm64 exec nix-xd-arm nix build --no-link --print-out-paths \
    'github:xd-dash/nix.xd/b7077d76d8036ae8eefe3b3c29ce559dfa1a8f61#storeProbeDynamic'
)/bin/hello"
```

Use the normal `make qualify-starwisp` arguments and add
`COREOS_GUEST_DYNAMIC_EXECUTABLE="$COREOS_GUEST_DYNAMIC_EXECUTABLE"`.
This gate executes the dynamic ELF directly from the shared Nix store,
including its interpreter and dependencies reachable through the same mount.

## Why retain 9P

For the current containerized QEMU on a Linux Podman Machine, 9P requires no
separate filesystem-export daemon or shared-memory backend. This is a
**configuration and operational complexity** preference, not a measured
performance result. VirtIO-FS may improve filesystem workload performance, but
typically requires `virtiofsd`, a Unix-domain socket to QEMU, and shared guest
RAM. Benchmark and permission comparison are deferred.

Unix socket path visibility is **not** host/guest socket connectivity.
Use a dedicated transport (e.g. QEMU VirtIO serial/host Unix socket,
virtio-vsock where supported, or authenticated networking) for cross-VM IPC;
keep runtime IPC out of the read-only Nix store export.

## Outstanding qualification work

- Prove dynamic ELF interpreter and multi-file closure execution on CoreOS.
- Validate full OCI archive format and integrity, not merely its gzip header.
- Verify Nix binary-cache substitution independently from `.tar.gz` archive readability.
- Add cross-VM IPC transport only with explicit need and isolation requirements.
- Compare VirtIO-FS with 9P only after these correctness gates.

## Bootstrap ownership and Nix-Alpine consumer gates

The host-side Podman bootstrap is authoritative for the named `/nix` volume.
`bin/nix-xd-store-export-check` now verifies the persistent `nix-xd-arm`
container mounts the **same named volume** read/write at `/nix`, that the
Nix CLI can query its store, and that separate rootless containers can only
read the exported volume. This verification is part of `make bootstrap`
for the Podman provider and is independent of a QEMU boot.

The CoreOS guest is deliberately not another writable Nix store owner.
Its `/var/mnt/nixstore` is a read-only 9P view of that volume; rootless
Podman uses a guest-local disposable rootfs and bind-mounts the immutable
store at `/nix/store`. The bootstrap is BusyBox, not a copy of an OCI image.

`storeProbeNix = pkgs.nix` is an additional optional closure and
`COREOS_GUEST_NIX_EXECUTABLE=/nix/store/.../bin/nix` tests a Nix CLI process
inside guest rootless Podman. It executes `nix --version` (read-only) through
that store mount. This proves the dynamic Nix CLI closure can start there;
it **does not** qualify full nested Nix-Alpine OCI bootstrapping or Nix
build/write operations inside CoreOS. Such operations require an explicit
separate writable metadata and output store or a remote Nix daemon interface.
There must never be a second unsynchronized writer to the host store.

These changes replace the previous assumptions that 9P itself can provide
a writable Podman rootfs or that merely opening an OCI `.tar.gz` proves
an executable Nix-Alpine container. Those bootstrap strategies are retired.
The 2026-11-08 static BusyBox qualification remains the prior successful
baseline; the newly extracted helper and Nix CLI execution gate require
an additional runtime qualification before promotion.

For the optional Nix CLI gate, build the pinned `#storeProbeNix` output
inside the running ARM Nix-Alpine and append `/bin/nix` to that store path;
pass it as `COREOS_GUEST_NIX_EXECUTABLE` to `make qualify-starwisp` together
with `COREOS_GUEST_PROBE_ROOTFS`, the existing 9P volume, and the prior
Starwisp credentials and QEMU settings.

## Bootstrap redesign: no image-to-store copying (not yet runtime-qualified)

The ARM image is now an Alpine bootstrap **without a Nix package store in
its OCI layers**. `arm/init-nix-store.sh` is the container entrypoint; it
installs single-user Nix directly into the final `/nix` volume on its first
start, marks it `.nix-xd-direct-volume-v1`, and fails closed for unexpected
nonempty/unmarked stores. The Podman Quadlet and Apple Container provider both
attach their named volume before the first Nix invocation. Apple Container no
longer runs `cp -a /nix/. /seed/`.

Do not run `make bootstrap` with the new image against an existing legacy
Nix volume without a deliberate maintenance plan: such a volume will be
rejected as incompatible. **No in-place copying, repair, migration, or
automatic deletion is authorized.** An operator must first preserve whatever
historical qualification evidence or artifacts are required, stop workloads,
and choose a clean redeployment with an explicitly selected empty volume.
Only after successful runtime qualification should the old infrastructure be
retired. The historical 9P/BusyBox success pertains to the earlier bootstrap
image and must not be represented as qualification of this new bootstrap.

Podman Machine and Apple Container are independent providers with independent
volumes; they must not be presented as simultaneously using one physical Nix
store. The canonical Starwisp path uses Podman Machine `coreos-arm64` and
volume `nix-xd-arm-store`. Switching providers is a deliberate redeployment,
not a file-level transfer.

The native Linux x86_64 `dash-xd/nix-alpine` upstream context has a separate
bootstrap implementation and is **not** certified by this ARM-only migration.
