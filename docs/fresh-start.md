# Fresh development sandbox

Nix-Alpine supplies generic execution capabilities. Make selects the runtime and
launches project flakes. Agni owns CoreOS machine construction, startup,
applications and their qualification. Grumble owns Grml image construction and
qualification. Neither project's policy belongs in the runtime.

## Resource identity

New builder containers and store volumes carry io.nix-xd labels for managed
ownership, scope, role and lifecycle. Quadlets also record composition and
placement. Runtime images carry component identity independent of any deployment.
LIFECYCLE=reusable is the default; disposable is an explicit classification.
A label does not automatically delete a volume. Existing resources are not
renamed or silently adopted.

Run `make runtime-inventory` to list resources, including legacy unlabelled
containers. On a Mac it inspects running Podman Machines and Apple resources;
stopped machines are reported and left stopped. Container mount sources are
included; environment variables and credentials are not dumped. This command
cannot inventory containers inside a CoreOS guest; Agni must supply that
guest-level inventory through its transport.

## Logs

The default is the checkout's untracked .logs directory.
Set NIX_XD_LOG_DIR to an absolute path, for example:

```sh
export NIX_XD_LOG_DIR="$HOME/.local/nix.xd/logs"
```

Filenames contain scope, action, composition, provider machine, host/guest
placement, container identity, timestamp and process ID. Callers identify nested
operations with NIX_XD_LOG_COMPOSITION, NIX_XD_LOG_MACHINE,
NIX_XD_LOG_PLACEMENT and NIX_XD_LOG_CONTAINER. Legacy callers default to
infrastructure/host identities until their project adapters supply these fields.
Credentials must never be printed by the command being logged.

## Images and storage

Nix owns dependency and application layering. Generic base containers receive
additional capabilities through explicit mounts and project flake execution.
OCI is an image format, independent of Apple's runtime.

`make image-export` saves the selected local image as a gzip-compressed OCI
archive and validates its OCI layout. Defaults:

```text
.artifacts/<composition>/<placement>/<scope>/images/<system>/sha256-<archive-digest>/
  image.oci.tar.gz
  manifest.json
```

Override ARTIFACT_ROOT to place artifacts outside a checkout. COMPOSITION_ID and
PLACEMENT_ID determine logical path components. The digest identifies archive
bytes; it is not the image manifest digest. A dockerTools Docker archive or
rootfs tarball is not automatically an OCI archive.

Volumes remain provider-local. Two containers in the same Podman Machine can
explicitly share a volume; macOS cannot directly mount that Linux volume.
Use explicit host bind mounts or an export/import capability for host access.
One builder owns each writable Nix store. PEER_STORES selects existing stores
read-only at /peer/<name>; a missing peer fails. Mounting a peer at a different
path does not make its absolute /nix/store references executable. Use the
qualified chroot-store view when execution from an adjacent store is required.

## Reset the known old sandbox

These commands permanently remove the named Podman Machine, its stores and VM
disks, and the listed checkouts. They do not preserve uncommitted changes or
credentials stored there. They leave SSH keys, Git credentials, unrelated
repositories and other Podman Machines alone. Run from your Mac:

```sh
cd "$HOME"
podman machine rm --force coreos-arm64
```

If the retired Apple image/build environment is still present:

```sh
container builder stop
container builder delete
container image delete localhost/nix-xd:arm64
```

Use inventory to identify any remaining Apple Nix-Alpine container or volume;
delete only those named resources. Do not prune all Apple resources.

```sh
cd "$HOME"
rm -rf -- \
  "$HOME/workspace/nix.xd" \
  "$HOME/workspace/nix.xd-consolidated" \
  "$HOME/workspace/nix-xd-fatline" \
  "$HOME/.local/state/nix-xd"
mkdir -p "$HOME/workspace" "$HOME/.local/nix.xd/logs"
git clone --single-branch --branch codex/generic-runtime-state \
  https://github.com/xd-dash/nix.xd.git "$HOME/workspace/nix.xd"
cd "$HOME/workspace/nix.xd"
cp examples/runtime-arm64-podman.mk nix-xd.local.mk
make runtime-contract-check
make check-static
```

The example selects the shared log/artifact directories outside the checkout.
No old runtime-state migration is needed for this reset.

## Project composition outline

Keep independent source checkouts next to nix.xd:

- Agni: its flakes declare CoreOS, ingress, Fatline services, activation,
  readiness, recovery and application qualification.
- Grumble: its flakes declare Grml build, inspect, boot and measurement apps.
- Nix-Alpine: generic builders, persistent stores, selected peer mounts,
  namespaces, image archives and project-flake launch capabilities.
- Smoke/Wisp: reusable execution, credential and transport capabilities.

Projects select explicit persistent stores and runtime inputs through the
generic launcher. Make remains the host control-plane. Project orchestration
executes inside Nix-Alpine; macOS-only socket operations require an explicit host
adapter.

Legacy Fatline/Starwisp controllers and application tests remain in this branch.
They require extraction into Agni before the repository can be described as
fully application-neutral. This resource foundation does not perform that
extraction or rerun application reliability qualification.
