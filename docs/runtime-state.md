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

### Credential boundary

`GRANTS_FILE` can represent secret and non-secret Podman state volumes. The persistent Nix-Alpine owner may read a secret volume **only if intentionally authorized to access everything on that volume**; a mounted path grants container-level visibility, not per-flake isolation. Use a dedicated UID/GID, user namespace and SELinux category or a dedicated qualification container when independent access boundaries are required. Private age identities may live persistently in protected Podman secret volumes, but never in Nix derivations or `/nix/store`; decrypted material should remain process-scoped.

The new grant documents complement the historical `shared-store-matrix.nix`; they do not change its previously qualified `common` store domain or automatically activate its deferred guest-local and guest-shared domains. A common matrix-domain-to-state-grant adapter remains an integration step.

## Secret domain: same Podman volumes, tighter grants

The generic state-volume controller accepts `STATE_KIND=secret`, producing a labeled `nix-xd-state-secret-<name>` volume. The generic `runtime_grants.py` parser accepts the same volume with `ro` reader or `rw` owner-only grants. This means encrypted SOPS documents and runtime age identities can be stored on persistent Podman volumes instead of ad hoc file-copy handoffs.

**Mount permissions are necessary but not sufficient for secrets:** a `ro` bind denies writes but does not distinguish two processes inside the same container. Container/user-namespace boundaries and Unix DAC/ACLs must restrict which readers can open age identity files. SELinux MCS can add further separation within the Podman Machine, but `:z` explicitly provides a shared label and is not an exclusive grant; `:Z` gives one container a private label and must not be indiscriminately applied to a deliberately shared volume. Never use a blanket `:U` ownership rewrite on a shared secret store.

The same named secret volume can be attached `ro` to authorized containers and `rw` to its designated owner. Any mounted consumer allowed to read the private age identity can decrypt ciphertext for the keys it authorizes. For a workload requiring decryption, prefer a process-scoped decryption environment (tmpfs or memory-backed file) and retain only the encrypted document and age identity in the persistent volume. Nix derivations and `/nix/store` must not contain the private key or decrypted plaintext.

For CoreOS, Podman mounts the selected volume into the QEMU runner and QEMU can export it using virtio-9P. This is a **separate Linux permission boundary**: guest UID/GID interpretation and 9P security model must be verified, and Podman SELinux labels do not automatically become enforceable guest MCS policies. Start read-only, with an explicit mapping and guest-side access test. No existing VM is implicitly modified.

Example new empty secrets volume (no key migration):

```sh
make state-volume-provision MACHINE=coreos-arm64 STATE_KIND=secret STATE_NAME=qualification
```

This establishes only a labeled volume, not encryption, permissions, tenant grant enforcement, or CoreOS 9P attachment.

## Isolated volume and CoreOS 9P qualification progression

`make grants-isolation-qualify` uses a disposable, rootless Podman fixture on the selected Linux Podman Machine. It requires enforcing SELinux, uses two disjoint UID/GID maps, and creates brand-new labeled fixture volumes for private identity, read-only input, and writable evidence. It verifies that a matching authorized identity can read the fixture identity and produce evidence, an unrelated mapped identity cannot read the identity, and both are denied writes to read-only inputs. The fixture does not use live SOPS/age keys and does not change VM1.

`make guest-9p-plan GRANTS_FILE=...` validates a schema-1 CoreOS 9P export declaration. `guest-9p-preflight` verifies its named Podman state volumes exist and retain their exact ownership labels. It does not start or alter a VM. `COREOS_9P_GRANTS_FILE` is an opt-in host adapter input for **newly created** CoreOS QEMU runner containers: it binds those volumes read-only under `/run/nix-xd/9p/<tag>`, passes read-only virtio-9P device arguments to the existing Agni QEMU runner, and records the declaration digest in the VM manifest. The managed-start path refuses a changed or missing declaration for an existing VM, rather than silently swapping attached storage. Existing VM1 is unaffected when the option is omitted.

**Still unqualified:** mounting the new tag inside CoreOS at a guest path, checking guest-side UID/GID/DAC and SELinux policy semantics, and the complete Logma resource roundtrip. A guest with new 9P hardware needs an Agni-owned guest mount declaration (for example, Ignition/systemd), and a disposable CoreOS runtime gate before activation on a persistent VM. The existing `nixstore` 9P export remains separate from all data and secret exports.
