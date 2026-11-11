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
