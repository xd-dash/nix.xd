# Tenant filesystem isolation gate

Run `make tenant-storage-qualify` from the selected runtime checkout. The common
logger records the complete run. This creates disposable filesystem fixtures,
not production tenant stores. It does not modify the existing primary or chroot
stores, restart their builder, or run Nix builds in tenant containers.

On macOS the host adapter runs the generic script on the selected Podman
Machine's Linux host. It does not create or qualify an additional Agni CoreOS
guest. The identical Linux script is also a flake app, tenant-storage-qualify,
for Agni to execute through its guest transport when that deployment is ready.
CoreOS machine construction and tenant application composition remain Agni's
responsibility. This first gate qualifies the storage primitive only.

## Identities and grants

Two disposable containers run as UID/GID 1000 inside separate explicit rootless
mapping ranges. The test reserves intermediate ranges 32768..40959 and
40960..49151 for its fixtures. It checks the available subordinate IDs before
creating containers, then records the actual initial-host UID/GID maps and
effective host identities. Tenant ranges must not overlap each other or contain
the ordinary builder's effective UID/GID. These fixed fixture ranges are not a
production tenant-ID allocator.

Each tenant creates its own protected directory under a private named volume.
Its root is mode 0700 and its volume has a private SELinux MCS label. No Podman
socket or management credentials are mounted into either tenant. Both run with
no effective capabilities, no network and a read-only container root filesystem.
The trusted controller alone manages container mappings and volume grants.

The gate proves:

- Both tenants can create and read their own private files.
- Cross-tenant reads fail even when the controller deliberately attaches the
  foreign volume read-only for a negative test.
- DAC independently denies the foreign mapped identity on a shared-label fixture.
- SELinux independently denies a foreign MCS level on a world-readable fixture;
  the same mapped identity with the authorized label can read it.
- Both tenants can read an explicitly shared artifact mount and cannot write it.
- The ordinary Linux host identity cannot browse either private backing path.
- A probe using the ordinary Nix builder's mapping and identity cannot read a
  tenant's private volume, even with a read-only attachment.
  If that builder shares Podman's rootless user namespace, the probe reuses it
  directly instead of attempting setns into its current namespace. The probe
  verifies its namespace inode, UID/GID and zero effective capabilities before
  testing access.
- The deletion helper refuses an in-use volume. After stopping/removing tenant A,
  it deletes A's private volume while B retains its container ID, data and grant.

The readable MAC fixture is deliberately separate from the private stores.
Its permissive Unix modes let the test isolate SELinux behavior without weakening
the private stores. No probe disables SELinux, adds capabilities or relabels a
foreign volume. Chown/relabel operations apply only to new disposable fixtures.

## Deletion authority

The helper derives a volume name from scope, tenant and store identity, verifies
all management labels and disposable lifecycle, and calls Podman volume rm
without force. It never mounts or reads that volume's files to delete it.
It deliberately cannot delete production/reusable volumes or arbitrary paths.

The rootless Podman controller has management authority and can deliberately act
on behalf of a tenant; it is distinct from ordinary filesystem access by the
host user or Nix builder. This is not an authenticated tenant-facing deletion API.
Smoke can later expose authorized lifecycle operations through that boundary.

Fixture containers and volumes are removed on completion or handled failure.
Logs retain the evidence; no fixture history or Nix-store migration is created.
The overall gate reports success only after cleanup succeeds.

## Remaining qualification

This gate does not yet prove actual Nix build execution under each tenant's
identity, a tenant runtime's restart/recreation contract, or storage isolation
inside a separately provisioned Agni CoreOS guest. Those must reuse this generic
primitive with their appropriate declared runtime profile. GCS/R2 mounts are
separate adapters and are not touched by this filesystem gate.
