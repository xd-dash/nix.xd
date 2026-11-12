# Runtime state ownership (Podman)

This document describes the generic state contract. It is **not** a completed migration of historical `.state/` or application data.

## Storage domains

- Each independent Nix writer retains its existing Podman named volume for `/nix`. Do not repurpose those volumes for mutable control-plane data.
- Control-plane metadata belongs in an independent, explicitly labeled state volume, mounted by an orchestrator adapter only after its lifecycle has been qualified.
- Each VM owns a distinct writable instance-state volume for its disk overlay. An immutable base image or Nix closure is a separate input, ideally mounted read-only.
- Application data and credentials belong to application-owned state volumes. The infrastructure provisions a volume on request without examining its data.
- Read-only Nix store closure sharing is independent of state-volume inspection or sharing. The qualified matrix is unchanged.

## Current opt-in interface

`bin/nix-xd-state-volume` and the Make targets support:

```sh
make state-volume-plan MACHINE=coreos-arm64 STATE_KIND=control STATE_NAME=orchestrator
make state-volume-provision MACHINE=coreos-arm64 STATE_KIND=control STATE_NAME=orchestrator
make state-volume-inspect MACHINE=coreos-arm64 STATE_KIND=control STATE_NAME=orchestrator

make state-volume-plan MACHINE=coreos-arm64 STATE_KIND=vm STATE_NAME=vm1
make state-volume-provision MACHINE=coreos-arm64 STATE_KIND=vm STATE_NAME=vm1

make state-volume-plan MACHINE=coreos-arm64 STATE_KIND=application STATE_NAME=example
```

Volume names are deterministic: `nix-xd-state-<kind>-<name>`. Volumes are labeled with a version, kind and logical name. Existing unlabeled volumes are never implicitly adopted. Provisioning is idempotent and never deletes an existing volume.

An optional host-side read-only archive export requires an explicit destination and refuses to overwrite it:

```sh
make state-volume-export MACHINE=coreos-arm64 STATE_KIND=control STATE_NAME=orchestrator STATE_EXPORT_PATH="$HOME/state-export.tar"
```

The exported archive can contain private application state. Access to it must be restricted. The export uses the locally cached Alpine image and does not pull it automatically.

**Provisioned volumes are not mounted automatically.** A new control volume is empty, and a new VM volume does not contain an existing CoreOS guest disk. Do not switch any running instance to one of these volumes before an offline migration and verification.

## Read-only migration preflight

Use the actual existing runner name, not a guessed mapping. This command verifies the new VM target volume exists with the correct ownership labels and is not mounted, then prints the current container image identity, state, writable `/state` bind source, read-only `/artifacts` source (if any), and shared-store mount. It performs no writes, stops, or guest disk operations.

```sh
make vm-state-preflight MACHINE=coreos-arm64 VM_CONTAINER=coreos-starwisp-r977b354c1cb8 VM_INSTANCE=vm1
make vm-state-preflight MACHINE=coreos-arm64 VM_CONTAINER=coreos-store-matrix-vm2 VM_INSTANCE=vm2
```

The preflight does **not** inspect the QCOW2 backing chain or prove guest readiness. It is deliberately not the migration operation. Check backing paths and quiesce the guest before any disk copy. If the current runner mounts the same location at both `/state` and `/artifacts`, preserve that identity or explicitly rebase and validate the disk chain.

## Default host paths

Host-side command logs default to `${XDG_STATE_HOME:-$HOME/.local/state}/nix-xd/logs` (overridden with `NIX_XD_LOG_DIR`). Generic source staging resolves relative to the parent workspace directory, not inside the `nix.xd` repository.

Legacy CoreOS commands still use `COREOS_STATE_ROOT` and may fall back to `.state/coreos`. This legacy behavior is deliberately retained until an instance-by-instance disk migration has passed; changing this default before a migration would orphan the existing VM's disk binding.

## Migration gates before deleting checkout-local state

1. Inventory every running/stopped Podman VM runner and its actual mount type, source, and destination. Identify any `/state` bind mount rooted in `~/workspace/nix.xd/.state`.
2. For each VM, record the container image digest, guest boot identity, QCOW2 backing references and base-image digest.
3. Stop the specific VM and verify the QCOW2 overlay is not being written.
4. Copy persistent guest data into a new instance volume. Verify the overlay/backing chain, ownership and hashes. Retain the original directory as a rollback copy.
5. Recreate the runner with a volume mount, bring up the guest and verify boot identity, store-sharing invariants and application-owned readiness.
6. Only after all consumers have been reconciled should historical state be archived or deleted.

Existing Nix writer volumes and the qualified read-only store matrix must remain unchanged.

## Repository ownership

This initial implementation establishes a generic storage interface only. The older application-specific CoreOS/Starwisp, Smoke and Fatline qualification modules and fixture declarations still need extraction to their respective repositories before `nix.xd` can be considered application-neutral. Do not interpret a static storage-contract PASS as proof of full separation.

## Composable workload state grants (candidate integration)

The existing `bin/nix-xd-state-volume` remains the authority for named state-volume creation and identity labels. `lib/runtime_grants.py` consumes a caller-selected JSON document (schema 1, runtime scope, and an explicit list of reader/writer/access grants). It **only** accepts labeled `nix-xd-state-{control,vm,application}-<name>` resources and destinations under `/run/nix-xd/mounts/<alias>`. These grants do not replace the tenant-storage policy: hostile-tenant private volumes are deliberately excluded.

The same declaration can be rendered to existing `DATA_MOUNTS` Quadlet syntax at bootstrap. `GRANTS_FILE` selects it without hand-constructing mount arguments:

```sh
make grants-plan GRANTS_FILE=/absolute/path/to/runtime-grants.json
make grants-render GRANTS_FILE=/absolute/path/to/runtime-grants.json
# A *future planned* builder recreation may select:
# make bootstrap PROVIDER=podman GRANTS_FILE=/absolute/path/to/runtime-grants.json
```

`make grants-verify GRANTS_FILE=... MACHINE=... SCOPE=...` reads Podman volume labels and actual container mounts, verifies exact source/path/access identity and read permission from the running container, and refuses another writable attachment when a volume is granted `rw`. This is a **post-mount verification**; it does not provision or activate a mount, migrate data, or prove a snapshot across process races.

For a non-secret macOS-to-Podman-Machine host bind fixture without modifying an existing container:

```sh
make grants-host-share-qualify PROVIDER=podman ARCH=arm64 SCOPE=nix-xd-arm
```

This temporary network-disabled Podman reader proves one read-only host fixture is visible through the Podman Machine at the same SHA-256 and not writable. It does **not** mount an SSH identity, add a CoreOS 9P filesystem, or imply the active Nix-Alpine owner has the new grant. Existing 9P sharing continues to apply only to the qualified read-only Nix store. Grant-to-9P guest exports and per-workload private credential bindings require separate adapters and qualification before a general end-to-end pass is claimed.
