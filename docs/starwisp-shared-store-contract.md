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
