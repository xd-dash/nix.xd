# nix.xd

A small host installer for a rootless Podman + systemd/Quadlet Nix-Alpine service.
This does not install NixOS or change host packages.

| Host | Build context |
| --- | --- |
| x86_64 Linux | `arm/` shared direct-volume OCI context; native Podman/Quadlet |
| ARM64 Linux (aarch64) | `arm/` shared direct-volume OCI context; Mac Podman Machine |

The separate `nix-alpine` flake source is pinned to upstream commit 80a2821b7571edd09507f9b4349e2f1ed3daf900. Its Dockerfile is not used for the direct-volume runtime bootstrap.


## Generic Make orchestration on Apple Silicon

The ARM Makefile follows the developing x86-64 Nix-Alpine interface at
`dash-xd/nix-alpine/local/Makefile` (branch `codex/coreos-fatline-qemu`).
The host runtime provider is independently selected by
`PROVIDER=podman|container`, default `podman`. The host does **not** need
Nix installed. Agni or another application's flake owns its own capabilities.

```sh
mkdir -p ~/workspace
git clone https://github.com/xd-dash/nix.xd.git ~/workspace/nix.xd
cd ~/workspace/nix.xd
make bootstrap PROVIDER=container         # native Apple container (macOS 26+)
make status PROVIDER=container
```

Use `make bootstrap` for the default Podman Machine + rootless Quadlet path.
Neither bootstrap installs, runs, or hardcodes Agni.

### Apple Silicon Podman Machine provisioning

`make machine-init` is an explicit, logged, idempotent machine creation command.
It uses `applehv` unless `MACHINE_PROVIDER=libkrun` is requested.
The default new-machine profile is 6 CPUs, 8192 MiB RAM, and 120 GiB
virtual disk. Nothing is removed or resized automatically.

```sh
# Provision a separate CoreOS-capable machine; preserve existing podman-machine-default
make machine-init MACHINE=coreos-arm64 MACHINE_PROVIDER=applehv \
  MACHINE_CPUS=6 MACHINE_MEMORY_MIB=8192 MACHINE_DISK_GIB=120

# Inspect the existing VM against the desired minimum, without altering it
make machine-check MACHINE=podman-machine-default \
  MACHINE_CPUS=4 MACHINE_MEMORY_MIB=8192 MACHINE_DISK_GIB=100

# Optionally provision and bootstrap Nix-Alpine as one step
make bootstrap PROVIDER=podman MACHINE=coreos-arm64 \
  MACHINE_BOOTSTRAP=1 MACHINE_VERIFY=1 \
  MACHINE_CPUS=6 MACHINE_MEMORY_MIB=8192 MACHINE_DISK_GIB=120
```

`MACHINE_BOOTSTRAP=1` creates a missing machine during `make bootstrap`;
`MACHINE_BOOTSTRAP=0` requires an existing machine. Explicit
`make machine-init` and `make machine-check` require the existing machine
to meet the requested minimum resources. By default `make bootstrap`
preserves and warns about an undersized existing machine, rather than
resizing or deleting a persistent VM; set `MACHINE_VERIFY=1` to fail closed.
`MACHINE_DEFAULT=1` opts into changing Podman's default system connection.
All operational `nix.xd` commands select `MACHINE` explicitly, so this
global change is not required.

For the existing Starwisp case, **no Nix-Alpine rebootstrap is needed just
to run the already-built CoreOS disk in Agni's QEMU container**. The QCOW2,
Ignition, and build manifest are on macOS; transfer the Agni runner image,
shut down the old VM, and select the new VM:

```sh
make machine-init MACHINE=coreos-arm64 MACHINE_MEMORY_MIB=8192
make machine-handoff FROM_MACHINE=podman-machine-default MACHINE=coreos-arm64
make coreos-preflight PROFILE=starwisp
make coreos-boot PROFILE=starwisp COREOS_RAM_MIB=2048
make coreos-qualify PROFILE=starwisp COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

If a previous, failed boot left `overlay.qcow2` on macOS but its
container remains on the stopped source machine, archive it explicitly
before booting on the new machine:

```sh
make coreos-reset-failed PROFILE=starwisp \
  COREOS_ORPHANED_OVERLAY=1 FROM_MACHINE=podman-machine-default
```

This refuses to archive a stale overlay unless the original machine is
stopped and the runner identity in the manifest matches the selected OCI
image. The overlay, serial log, and manifest are retained in a dated
`failed-*` directory; `base.qcow2`, `config.ign`, and `build.txt`
are left intact. Do not enable this for a guest that may still be running
on another machine.

The handoff serializes the specified OCI image to a temporary host archive,
stops the old VM, starts the new VM, loads the image, checks that the image
digest is unchanged, and writes the selected machine into
`.state/active-podman-machine`. Operational Make commands use that selection
unless `MACHINE=...` is specified. This is not a Nix-Alpine store migration:
the old machine, its persistent `/nix` volume, original image store, and
Quadlet remain untouched. To run generic Nix tasks in the new VM, restore
or migrate its Nix-Alpine environment separately. Preserve the original VM
until its store is accounted for; cleanup is intentionally not automatic.

Creating a new Podman Machine creates a **separate** Podman image and volume
store. The existing Nix-Alpine store is not migrated automatically. After
bootstrapping the new machine, use the same `make sync`, `stage`, `build`,
`run`, and `qualify` commands as with the original machine, setting
`MACHINE=coreos-arm64` for provider-backed operations. Nix owns
application-level execution; the host Make targets only bootstrap or provide
required runtime transport.

### Generic source and flake interface

`WORKSPACES` defaults to the `nix.xd` checkout root. This matches the x86
layout's `/workspaces` convention. A checkout name may include subdirectories
such as `compositions/agni`.

```sh
make sync REPO=dash-xd/agni \
  BRANCH=codex/coreos-fatline-qemu \
  SYNC_NAME=compositions/agni

make stage CHECKOUT=compositions/agni PROVIDER=container
make show FLAKE=compositions/agni/qemu/coreos-live PROVIDER=container
make build FLAKE=compositions/agni/qemu/coreos-live TARGET='#output' PROVIDER=container
make run FLAKE=compositions/agni/qemu/coreos-live TARGET='#app' PROVIDER=container
```

`#output` and `#app` are illustrative; check `make show` before selecting
an output. The old Agni CoreOS flake has known incomplete hashes and is **not**
already qualified for ARM. `make build` now means **Nix build** as on x86;
`make image-build` builds the Nix-Alpine OCI image.

`make sync` clones or fast-forwards `REPO` at `BRANCH`, checks the remote,
refuses tracked edits, and accepts `REV=<full-40-character-SHA>` as a
fail-closed revision fence. `make stage` copies the committed Git snapshot,
excluding untracked files and `.git`, from the requested checkout to
`/workspaces/<checkout>` in the selected runtime. Re-stage after changing
the source. No host socket, host systemd bus, or broad host workspace mount is
granted to the Apple provider.

`make show`, `check`, `build`, `path-info`, `run`, and `develop`
delegate to Nix inside the selected Nix-Alpine container and accept `FLAKE`
and `TARGET`. `make compose`, `qualify`, `qualify-process`,
`qualify-service`, and `qualify-composition` select application-owned Nix
app outputs, failing if unavailable. `make qualify-plan` requires an explicit
`PLAN_TARGET`; it does not emulate x86 host-Podman qualification or assert
that a CoreOS VM booted. `ARGS` is a whitespace-delimited argument list;
use `make exec CMD='...'` for shell commands.

### Diagnostic logging and repeatable bootstrap

Noninteractive `make bootstrap`, `sync`, `stage`, `show`, `check`,
`build`, `path-info`, and `run` commands write live output to the terminal
and a timestamped file in the tracked `logs/` directory. Generated `*.log`
files are Git-ignored. Filenames include the scope, operation, UTC timestamp,
and process ID (for example `nix-xd-arm-bootstrap-20261105T221100Z-1234.log`).
`NIX_XD_LOG_DIR` can override the destination. The wrapper preserves the
underlying command's failure status and prints the resulting log path.

```sh
make bootstrap PROVIDER=container SCOPE=nix-xd-arm
ls -t logs/nix-xd-arm-bootstrap-*.log | head -1
tail -f "$(ls -t logs/nix-xd-arm-bootstrap-*.log | head -1)"
```

Apple Container bootstrap checks for an existing runner **before** trying to
attach its named Nix store to a temporary seed container. An existing container
is reused only if its expected image reference, named volume, ext4 mount, and
seed marker match. A stopped matching container is started. Unexpected state
fails closed without deleting the container or store. An absent runner causes
the volume to be created if needed, seeded once, and attached to the runner.
Do not execute two bootstraps for the same scope concurrently.

The ARM task runner explicitly selects `aarch64-linux` through the Nix
`system` option. Flake evaluation remains pure by default; no global
`--impure` flag or reliance on `builtins.currentSystem` is introduced.

### Providers and boundaries

- **Podman (default):** Apple Hypervisor-backed Linux VM with rootless
  systemd/Quadlet for persistent container lifecycle.
- **Apple container:** Native `container` CLI, per-container micro-VM,
  persistent named `/nix` volume, no Podman Machine or Quadlet.
- Both use the `arm/Dockerfile` OCI image and the same generic Nix task
  interface. Image stores and volumes are independent.
- The current ARM Make execution is **not runtime qualified** on a Mac.
  `make check-static` only validates source syntax and Make expansion.

Agni remains the authority for QEMU/CoreOS/Farcaster configuration and optional
Wisp/Fatline behavior. Running nested accelerated QEMU from Apple's container
runtime cannot be assumed.

### ARM64 Agni QEMU OCI runner on Podman Machine (default)

The default CoreOS VMM is now `podman`. QEMU runs **inside the Nix-built Agni
ARM64 OCI container**, not through Homebrew. It uses software TCG emulation
inside Podman Machine, because the Linux guest VM cannot directly use macOS HVF.
The existing `VMM=hvf` adapter is optional for host-accelerated experiments.

Agni's development branch `codex/coreos-arm64-qemu-container` adds the
`#qemuRunner` Nix OCI archive and pinned Fedora CoreOS `#qcow` ARM64 disk.
The existing `x86_64-linux` outputs are preserved.

Starwisp Ignition is now compiled from Agni's pinned Butane profile by
`make coreos-ignition-build`. The guest receives a dedicated non-wheel `wisp`
account with SSH authorized keys and a lingering systemd user manager.
Generate a disposable ED25519 keypair locally and pass only the public key
to the Agni Nix derivation. Keep the private key off the Nix store:

```sh
ssh-keygen -q -t ed25519 -N '' -f "$HOME/.ssh/starwisp-test"
make coreos-ignition-build PROFILE=starwisp \
  COREOS_SSH_PUBLIC_KEY="$HOME/.ssh/starwisp-test.pub"
make coreos-preflight PROFILE=starwisp
make coreos-boot PROFILE=starwisp
make coreos-qualify PROFILE=starwisp \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
make coreos-stop PROFILE=starwisp
```

Run the Ignition build only after the updated Agni branch is synchronized
and staged again, since the Starwisp profile is in Agni's flake sources.
Existing `base.qcow2` is reused and is not rebuilt. Preflight checks disk
and Ignition digests, QEMU runner image identity and firmware availability.
Guest boot and its negative-path Wisp gates still require a real ARM64 run.

```sh
cd ~/workspace/nix.xd
make bootstrap PROVIDER=podman SCOPE=nix-xd-arm
make sync REPO=dash-xd/agni BRANCH=codex/coreos-arm64-qemu-container SYNC_NAME=agni
make stage CHECKOUT=agni PROVIDER=podman
make coreos-container-build PROFILE=starwisp
```

`coreos-container-build` builds the Agni ARM64 OCI image with Nix inside
the persistent Nix-Alpine container, loads it into that Podman Machine,
and exports the checksum-verified ARM64 CoreOS QCOW2 into
`.state/coreos/starwisp/base.qcow2`. It does not invent an Ignition profile.
Agni/Smoke must produce a rendered `config.ign` in that directory with
the required unprivileged Wisp user, SSH key, enabled user systemd manager,
and rootless Podman readiness before attempting boot.

```sh
make coreos-preflight PROFILE=starwisp
make coreos-boot PROFILE=starwisp
make coreos-qualify PROFILE=starwisp COREOS_SSH_KEY=/path/to/ephemeral-key
make coreos-stop PROFILE=starwisp
```

The Podman adapter selects the configured machine's connection explicitly
and uses a named, disposable QEMU guest container and QCOW2 overlay.
Host state must be shared into Podman Machine. The guest SSH port is mapped
to loopback. Never treat a successful image build or static check as
evidence of successful CoreOS boot or Wisp execution.

### Optional shared Nix store over VirtIO 9P (experimental)

The host Nix-Alpine container is the **single writer** to its
`<scope>-store` named Podman volume. Bootstrap now checks that a separate
rootless container can read the volume at `/host-nix/store` through a
read-only mount as UID 0 and UID 1000; it never recursively changes
ownership or file permissions. On an already-bootstrapped host:

```sh
make store-export-check MACHINE=podman-machine-default SCOPE=nix-xd-arm
```

**The Podman Machine matters:** the currently qualified `coreos-arm64`
machine has the Agni QEMU image, while the original `nix-xd-arm-store`
lives in `podman-machine-default`. The store is not magically shared
across Podman Machines. This check must pass in the machine in which
the new QEMU guest will run.

To opt in, stage Agni's updated `codex/coreos-arm64-qemu-container`
revision and build its new `qemuRunner` and
`ignitionStarwisp9p` outputs in a machine with the Nix executor and
volume. Supply `COREOS_NIX_STORE_VOLUME=nix-xd-arm-store` to the
`coreos-ignition-build`, `coreos-preflight`, `coreos-boot` and
`qualify-starwisp` targets. The new runner supports
`run-shared-nix`: `nix.xd` mounts the volume read-only in the
runner and Agni configures a **read-only** VirtIO 9P export. Agni's
opt-in Butane profile mounts `nixstore` at
`/var/mnt/nixstore` in the CoreOS guest.

Do not reuse existing `config.ign` for this option:
`coreos-ignition-build` intentionally refuses overwriting it.
Create an independently scoped `COREOS_STATE_ROOT` and generate a fresh artifact set instead. Preflight checks
that the selected volume matches the Ignition generation manifest.

The host volume readability check does **not** establish that the
Fedora CoreOS kernel has the 9P modules or that a rootless guest Podman
container can bind the mount. Qualify both before storing a production
dependency on it:

```sh
# Inside the booted CoreOS guest, with an authorized administrative account:
findmnt /var/mnt/nixstore
stat /var/mnt/nixstore
# Then verify a rootless container can bind the mount read-only.
```

For nested Podman, use a rootless container `--mount
type=bind,src=/var/mnt/nixstore,dst=/nix/store,ro`; make its Quadlet
depend on `var-mnt-nixstore.mount` and refuse an absent mount.
SELinux/UID mappings must be verified with the real guest and image;
do not relabel the shared Nix store recursively. Nix databases and
garbage-collection metadata are **not** shared. The authoritative host
must keep GC roots for all closures still in use by guests.

### First live 9P CoreOS guest qualification

The host `make store-export-check MACHINE=coreos-arm64` passed for
`nix-xd-arm-store`. Use a **new artifact root and guest name** for the
9P experiment. Do not overwrite the previously qualified Starwisp data.

```sh
cd ~/workspace/nix.xd
git pull --ff-only
make check-static

make sync REPO=dash-xd/agni BRANCH=codex/coreos-arm64-qemu-container \
  REV=c0f4febb22cf7daa9af72e4e2298899a7c3c84a4 WORKSPACES="$PWD"
make stage MACHINE=coreos-arm64 CHECKOUT=agni WORKSPACES="$PWD"

# Keep a tag for the original, previously qualified OCI image.
podman --connection coreos-arm64 tag \
  sha256:f420b7ae6d47ab1762008d16341577a7990bc421310e377b8f43a0ced65e9091 \
  localhost/agni-coreos-qemu-runner:starwisp-qualified

export COREOS_STATE_ROOT="$PWD/.state/coreos-9p"
make coreos-container-build MACHINE=coreos-arm64 \
  COREOS_STATE_ROOT="$COREOS_STATE_ROOT" COREOS_NIX_STORE_VOLUME=nix-xd-arm-store
make coreos-ignition-build MACHINE=coreos-arm64 \
  COREOS_STATE_ROOT="$COREOS_STATE_ROOT" COREOS_NIX_STORE_VOLUME=nix-xd-arm-store \
  COREOS_SSH_PUBLIC_KEY="$HOME/.ssh/starwisp-test.pub"

make qualify-starwisp MACHINE=coreos-arm64 \
  COREOS_STATE_ROOT="$COREOS_STATE_ROOT" COREOS_NIX_STORE_VOLUME=nix-xd-arm-store \
  COREOS_CONTAINER_NAME=coreos-starwisp-9p \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test" COREOS_READY_TIMEOUT_SEC=900
```

This retains `nix-9p.log` with the qualification, and fails if
`findmnt` does not report a **9p** mount with **ro** options at
`/var/mnt/nixstore`, or the store cannot be read. It also exercises
Wisp's rootless systemd tests as before. The experiment's container
name is distinct; no already-qualified guest has to be deleted.

The first run does **not** claim to qualify the nested Nix-Alpine
container. To test nested rootless Podman after deliberately loading a
container image into the CoreOS guest, set
`COREOS_GUEST_PROBE_IMAGE=<existing-guest-image>` on the same qualification
target. The nested gate runs with `--pull=never`, binds the 9P store
read-only at `/nix/store`, and preserves `nix-9p-nested.log`.
No new service is installed; the optional `label=disable` is limited to
this diagnostic container and must be reviewed for later production use.

**9P kernel capability is not assumed.** If the mount fails, preserve
the serial log and `nix-9p.log`; the CoreOS kernel configuration must be
checked before using this path for a guest workload. The store volume
remains owned by the host Nix-Alpine instance.

### Repeatable Starwisp runtime qualification

After a one-time Agni build, Ignition generation, and OCI handoff to the
selected Podman Machine, run the complete guest qualification with:

```sh
make qualify-starwisp \
  MACHINE=coreos-arm64 \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test" \
  COREOS_READY_TIMEOUT_SEC=900 \
  COREOS_READY_RETRY_SEC=10 \
  COREOS_RAM_MIB=2048 COREOS_CPUS=2
```

This checks the existing image, disk and Ignition SHA-256s against
`build.txt`, archives a prior **stopped** guest/overlay if present,
boots the same pinned QEMU image with a fresh writable overlay, emits
`SSH_WAIT` diagnostics during bounded SSH readiness, tests Wisp's
rootless systemd success/failure/timeout paths, and stops the guest.
A **running** guest, unrecognized overlay, mismatched hashes, or missing
private key fails closed. Existing image and `base.qcow2` are never
rebuilt or overwritten by this target.

Per-attempt evidence is saved under
`.state/coreos/starwisp/qualifications/<UTC>-<pid>/` including
`qualification.txt` (machine resources, nix.xd revision, Agni source
revision if available, OCI image ID, disk and Ignition digests, SSH public
key fingerprint, exit status), `run.log`, `wisp.log`, QEMU output and
serial/boot manifest copies. The old guest overlay, Wisp log, and host-key
record are archived under `failed-*` before a subsequent run.
`COREOS_AGNI_REV=<40-char-sha>` may be used to assert a local Agni
checkout revision; the local checkout revision does **not** independently
prove which revision was staged in the original Nix store, so the
record labels this source evidence accordingly.

You can inspect the newest result with:

```sh
ls -td .state/coreos/starwisp/qualifications/* | head -1
cat "$(ls -td .state/coreos/starwisp/qualifications/* | head -1)/qualification.txt"
```

Unlike `make coreos-qualify`, `make qualify-starwisp` owns the entire
boot/qualification/stop lifecycle. It requires the target Podman Machine
and its Agni QEMU image to already exist and be running/loaded; it does
not bootstrap Nix-Alpine or create a new Podman Machine.

### Optional host HVF adapter (not required for Podman mode)


CoreOS boot qualification runs directly on Apple Silicon macOS under QEMU/HVF,
not in Podman Machine or an Apple container micro-VM. Nix-Alpine prepares
artifacts; explicit export transfers them to the host before boot.

Provide a pinned aarch64 Fedora CoreOS QCOW2 disk, rendered Ignition JSON,
ARM64 UEFI firmware, and an ephemeral SSH key for an unprivileged guest user.
The guest must provision that user with a running systemd --user manager,
lingering, and rootless Podman. The adapter never downloads an OS image.

```sh
brew install qemu
export COREOS_IMAGE=/absolute/path/to/fcos-aarch64.qcow2
export COREOS_IGNITION=/absolute/path/to/starwisp.ign
export COREOS_FIRMWARE=/opt/homebrew/share/qemu/edk2-aarch64-code.fd
export COREOS_SSH_KEY=/absolute/path/to/ephemeral-test-key
export COREOS_IMAGE_SHA256="$(shasum -a 256 "$COREOS_IMAGE" | awk '{print $1}')"
make coreos-preflight PROFILE=starwisp
make coreos-boot PROFILE=starwisp COREOS_SSH_PORT=2222
make coreos-qualify PROFILE=starwisp COREOS_GUEST_USER=wisp
make coreos-stop PROFILE=starwisp
```

Verify the firmware path on the local Homebrew installation. The adapter
uses a disposable QCOW2 overlay and binds forwarded SSH to 127.0.0.1 only.
State is never overwritten. It retains a digest manifest, serial log,
Wisp stdout/stderr and the overlay in .state/coreos/PROFILE/.
Use a new profile for another run. After stopping, removing the profile
directory is an explicit cleanup operation.

The Wisp test requires unprivileged user systemd, rootless Podman, successful
transient service execution, failure propagation and RuntimeMaxSec timeout.
Boot/SSH/Wisp success is not full image or release qualification: artifact
export, provenance, Ignition provisioning, reboot and GCE-specific checks
remain distinct. No Podman engine socket is mounted inside Nix-Alpine.

## Usage

The host needs Nix with flakes enabled to invoke the installer, rootless Podman,
Quadlet, and an active systemd user session. ARM means ARM64, not 32-bit ARM.
Configure subordinate UID/GID ranges using your distribution's normal rootless
Podman setup. The installer does not use sudo or change lingering policy.

```sh
nix run github:xd-dash/nix.xd -- plan
nix run github:xd-dash/nix.xd -- install
nix run github:xd-dash/nix.xd -- start
nix run github:xd-dash/nix.xd -- shell
```

Add a scope as the second argument to isolate service/container/store names.
Install builds the native image, checks Nix, and writes a user Quadlet. It does
not start the service. Quadlet's Install section handles future user-session
startup; do not enable the generated service. For boot without login, explicitly
configure user lingering on the host.

Each scope owns one writable Nix store. Use this service as the single writer;
do not mount that store into other concurrent writers. No host directories or
container engine sockets are mounted. The service has outbound networking but
publishes no ports.

## Boundaries and qualification

This is an initial integration, not a production-qualified runtime.
The source pin does not make the container build reproducible: upstream uses
Alpine latest and a network Nix installer; the ARM context pins a release tag and
Nix installer version, but does not yet lock image/payload digests.
ARM has no native runtime qualification yet. No cross-emulation is configured.
The container's sandbox is disabled to match the existing single-user setup.

`nix flake check --all-systems` evaluates both systems; native builds should be
qualified separately on each architecture before relying on them.
The bootstrap transaction generates and checks flake.lock before publication.

Existing Quadlet files are never overwritten. To remove an installation, stop
its service, remove its exact .container file, and reload the user systemd
manager. Store-volume deletion is a separate explicit data-removal operation.


### Architecture selection and optional qualification modules

The orchestration entrypoint accepts `ARCH=arm64|amd64` (default inferred from the host).
The selected Linux Nix system is `aarch64-linux` or `x86_64-linux`. The generic
`run`, `show`, `build`, `check`, and flake-owned `qualify` paths check
the actual runtime architecture and fail on a mismatch. The macOS OCI bootstrap
adapter currently supports only Apple Silicon; the existing x86_64 Linux flake
installer remains a separate, unqualified-for-this-host bootstrap path.

`qualify` continues to use the selected application's `#qualify` output by
default. When `MODULES` is supplied, it executes named optional qualification
modules instead:

```sh
make qualify PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm ARCH=arm64 MODULES=secrets
```

Set `QUALIFY_APP=1` to run the application's `#qualify` output **and then** the
selected modules in one invocation; by default `MODULES=...` runs modules
alone, while omitting `MODULES` preserves the original flake qualification:

```sh
make qualify QUALIFY_APP=1 MODULES=secrets FLAKE=compositions/my-app ARCH=arm64
```

The `secrets` module uses Nix to provide age and SOPS executables inside the
running Nix-Alpine container. It generates a disposable age identity and test
JSON in a private `/tmp` directory, performs a SOPS encrypt/decrypt round trip,
and removes all runtime secret files with an exit trap. Private identities and
plaintext are never supplied as derivation inputs, command arguments, or log
output. The Nix store may cache the *age/SOPS binaries*, not the private identity.

This gate validates age/SOPS runtime operations, **not** persistent credential
bootstrap or Smoke's Go SOPS/age integration. Those are application-owned gates
and should be integrated as additional modules or flake-owned qualifiers rather
than adding top-level `secrets` orchestration commands.


### Common bootstrap contract and modular Makefiles

The repository has **one top-level Make interface** and included architecture
adapters in `mk/bootstrap-arm64.mk` and `mk/bootstrap-amd64.mk`:

```sh
# Apple Silicon/macOS: Podman Machine, ARM64 direct-volume Nix-Alpine
make bootstrap ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm

# Native x86_64 Linux: local rootless Podman and systemd user Quadlet
make bootstrap ARCH=amd64 PROVIDER=podman SCOPE=nix-xd-amd64
make qualify ARCH=amd64 PROVIDER=podman SCOPE=nix-xd-amd64 MODULES=store-recreation,secrets
```

Both bootstraps now build the **same source** (`arm/Dockerfile`, despite its
legacy directory name) for their respective architecture, and install Nix only
after mounting an empty, persistent `<scope>-store` volume at `/nix`.
They share the UID 1000 owner, `/nix/home/nixuser`, persistent profile,
`.nix-xd-direct-volume-v2` marker, and fail-closed refusal of unmarked
non-empty volumes. Neither bootstraps by copying an OCI-embedded Nix store.
They require rootless Podman and systemd's user manager.

The separate `dash-xd/nix-alpine` upstream source remains pinned in
`flake.nix` for existing flake outputs; its older image-baked Nix Dockerfile
is **not** used by the AMD64 direct-volume bootstrap. The previous AMD64
adapter that expected `local/bootstrap.sh` at that pinned commit was
incorrect; that file was absent from the pinned revision.

`MODULES=store-recreation` is a **shared qualification module**, not a new
top-level Make command. It restarts the user Quadlet, requires a changed
container ID, verifies the Nix executable path and SHA-256 and store mount
are unchanged, and checks read-only volume exports as UID 0 and 1000.
The same assertions run with local rootless Podman on native Linux or
through the selected Podman Machine from macOS. `make arm-qualify-recreation`
is retained as a compatibility entrypoint delegating to the shared module.

The common command interface has passed static CI and ARM64 bootstrap,
recreation, and secrets runtime qualification have passed on the Mac.
**Native x86_64 execution is not yet qualified** until the commands above
run successfully on an x86_64 Linux host.

Once Nix-Alpine is installed, the host Makefile is an operational launcher:
pinned flake outputs own deterministic application and host changes.
Make handles initial bootstrap, explicit runtime/service control, and
development-time refresh, not application-specific deployment mutations.

### Qualification source parity

ARM64 and x86_64 bootstraps may use distinct platform-specific Make adapters,
but the qualification **application logic** is shared in
`qualifiers/modules/`. On Apple Silicon, qualify the existing `coreos-arm64`
Podman Machine without rebuilding or resetting its Nix store:

```sh
make qualify ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 \\
  SCOPE=nix-xd-arm MODULES=store-recreation,secrets
```

The `store-recreation` module uses the same checks on macOS and Linux;
only Podman/Quadlet transport varies. Native AMD64 runtime qualification is
optional during ARM development: keeping its build bootstrap aligned does
not require a local x86_64 host or QEMU emulation. Runtime evidence must
still be collected separately before claiming that architecture qualified.


### Requalify Starwisp against the current ARM64 store

The `qualify-starwisp-shared` composition builds the pinned flake's
`storeProbeRootfs`, `storeProbeDynamic`, `storeProbeNix`, and
`storeProbeOciArchive` outputs in the existing Nix-Alpine owner. It
requires the complete closure of each output to be present, verifies the
authoritative owner/read-only export, checks the existing Starwisp build
manifest was configured for `nix-xd-arm-store`, and then invokes the
existing guest 9P/Wisp/nested-Podman qualification. It never resets or
copies the store, and refuses to overwrite existing disk or Ignition
artifacts.

Prepare the committed `nix.xd` flake inside Nix-Alpine. `WORKSPACES`
must be the parent of the selected checkout:

```sh
cd ~/workspace/nix.xd
make stage PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  WORKSPACES="$HOME/workspace" CHECKOUT=nix.xd
```

If Starwisp's existing `./.state/coreos/starwisp/build.txt` has the
`shared_nix_volume=nix-xd-arm-store` marker, qualify its existing
artifacts:

```sh
make qualify-starwisp-shared ARCH=arm64 PROVIDER=podman \
  MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

If that marker is missing or refers to another volume, **do not modify
the old artifacts**. Build a fresh, isolated Starwisp 9P disk and Ignition
under a separate state root. The ARM64 Agni source for these outputs is
`codex/coreos-arm64-qemu-container`, not the older x86_64-only
`codex/coreos-fatline-qemu` variant. Keep the existing Agni checkout
untouched by using a dedicated checkout:

```sh
cd ~/workspace/nix.xd
make sync REPO=dash-xd/agni BRANCH=codex/coreos-arm64-qemu-container \\
  REV=a49af1aa7a0f1d8dd792310391e9ed99ce865106 \\
  SYNC_NAME=agni-starwisp-9p WORKSPACES="$PWD"
make stage ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 \\
  SCOPE=nix-xd-arm WORKSPACES="$PWD" CHECKOUT=agni-starwisp-9p

state="$PWD/.state/coreos-9p-ordering-fixed"
agni_flake=/workspaces/agni-starwisp-9p/qemu/coreos-live/local

make coreos-container-build ARCH=arm64 MACHINE=coreos-arm64 \\
  SCOPE=nix-xd-arm COREOS_STATE_ROOT="$state" COREOS_FLAKE="$agni_flake" \\
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store

make coreos-ignition-build ARCH=arm64 MACHINE=coreos-arm64 \\
  SCOPE=nix-xd-arm COREOS_STATE_ROOT="$state" COREOS_FLAKE="$agni_flake" \\
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store \\
  COREOS_SSH_PUBLIC_KEY="$HOME/.ssh/starwisp-test.pub"

make qualify-starwisp-shared ARCH=arm64 PROVIDER=podman \\
  MACHINE=coreos-arm64 SCOPE=nix-xd-arm \\
  COREOS_STATE_ROOT="$state" \\
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store \\
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

The new `COREOS_STATE_ROOT` produces artifacts in
`./.state/coreos-9p-ordering-fixed/starwisp`. The old `./.state/coreos/starwisp`
remains untouched. The first command is pinned to an observed Agni
revision and will fail closed if that branch advances; update the
revision deliberately rather than silently building from an unknown
commit. The new Ignition must contain the 9P mount unit and produce
`shared_nix_volume=nix-xd-arm-store` in its build manifest.

The source and builds are still qualified under the existing Agni
profile gates; using the current Nix store alone is not evidence that a
past QEMU disk or Ignition remains compatible. A successful runtime
run requires `NIX_9P_GUEST_MOUNT`, `NIX_9P_OCI_ARCHIVE_READONLY`,
`NIX_9P_NESTED_EXECUTABLE`, `NIX_9P_DYNAMIC_CLOSURE_EXECUTABLE`,
`NIX_9P_NIX_CLI_READONLY`, and `NIX_9P_NESTED_PODMAN_READONLY`
from the guest, followed by `QUALIFY_STARWISP_RESULT status=passed`.

### Starwisp 9P systemd ordering correction (November 2026)

The earlier 9P Ignition was generated with `After=local-fs.target` in
`var-mnt-nixstore.mount`. Systemd also generated
`Before=local-fs.target` for the local mount, creating a contradictory
ordering constraint. The ARM64 Agni profile was corrected at revision
`a49af1aa7a0f1d8dd792310391e9ed99ce865106`; the mount now keeps
`Before=multi-user.target` but does not explicitly order itself after
`local-fs.target`. The old `config.ign` cannot be repaired by changing
its build manifest. Keep the previous `./.state/coreos-9p` run and its
logs for diagnosis; build a new 9P Ignition in
`./.state/coreos-9p-ordering-fixed` and do not reset the authoritative
`nix-xd-arm-store` volume. A runtime guest mount check is still required
before treating the ordering change as qualified.

### Authoritative Nix store GC roots

The authoritative Nix-Alpine container mounts `<scope>-store` at `/nix`.
The Starwisp shared-store qualifier can execute outputs through guest read-only
9P, but merely realizing them does not create durable GC roots.

`store-roots/starwisp.tsv` declares four outputs to retain, using names and
flake output identifiers instead of machine-specific Nix store hashes. Run:

```sh
make store-roots-inspect ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
make store-roots-apply ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
make store-roots-inspect ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
```

`store-roots-apply` requires the `nix.xd` flake staged at
`/workspaces/nix.xd` (from `~/workspace/nix.xd`, use
`make stage CHECKOUT=nix.xd WORKSPACES="$HOME/workspace" PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm` if absent).
The owner builds/validates each declared output; a narrowly scoped root helper
creates or atomically replaces symlinks beneath
`/nix/var/nix/gcroots/nix-xd/starwisp/`. It never deletes unrelated
roots or the store; previously registered roots not present in the current
declaration are deliberately retained until a separate prune policy is
introduced. These commands use the existing per-scope timestamped logs.

`make store-diagnose` now scans GC-root symlink metadata directly instead
of invoking `nix-store --gc --print-roots`, which can remove stale temporary
root files. This is a read-only snapshot of *links*, not an authoritative
live/dead closure computation.

Nix's experimental `local-overlay-store` is intentionally not enabled here.
It requires a guest-managed writable OverlayFS upper layer and an immutable
lower store while that overlay is mounted; our authoritative Nix-Alpine owner
is expected to continue adding paths. Use a separately qualified, immutable
lower-store snapshot only if guest-local Nix builds become a requirement.
The current execution model needs only the qualified read-only 9P export.

### Disposable GC retention qualification

Run the same GC retention fixture inside the existing Nix-Alpine owner:

```sh
make qualify ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 \
  SCOPE=nix-xd-arm MODULES=store-gc-retention
```

No staging or guest rebuild is needed. The host streams the fixture to the
owner, checks its architecture, UID and authoritative volume, then selects
an isolated `local?root=/tmp/...` store for every Nix operation. The fixture
checks that a direct root in `gcroots/nix-xd/starwisp` retains an output and
its dependency, an unrooted control is collected, and removing the root makes
both retained paths collectible. Temporary store state is removed on exit.
The authoritative store supplies the Nix CLI; GC only runs in the temporary
store. Expected completion markers are `STORE_ROOTS_GC_RESULT=passed` and
`QUALIFY_MODULES_RESULT=passed modules=store-gc-retention`.

The same module supports native AMD64 with `ARCH=amd64` and the matching scope.
CI runs the standalone fixture with Nix 2.34.9 on an Ubuntu x86_64 runner;
local module execution provides separate evidence for the installed runtime.

### Shared workload manifests and retained generations

`workloads.<system>.<name>` in the flake declares the rootfs, executable,
argument array, retained outputs, required guest capabilities, network policy,
timeout, and exit/output qualification. `starwisp-probe` is the first workload;
its declaration and controller have the same interface on `aarch64-linux` and
`x86_64-linux`. This does not claim native AMD64/CoreOS qualification.

`make stage` now records the committed source revision. Preparation checks that
revision, snapshots the staged flake to an immutable store path, and records its
NAR hash. It builds with output links in the authoritative owner's root namespace,
validates complete closures, and registers generation roots with Nix's native
GC coordination. Roots are stored at:

```
/nix/var/nix/gcroots/nix-xd/workloads/<workload>/<generation>/<output>
```

The source snapshot is retained too. Generations are hashes of the resolved
manifest and executor. A stopped generation gets a new identity if prepared
again, so delayed requests cannot restart a generation whose roots were released.
The controller uses Python's standard library, supplied by its Nix app; it
requires no Python installation inside the bootstrap image.

The common post-bootstrap interface is:

```sh
make workload-prepare ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
make workload-inspect ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
# The following target an already booted, qualified, shared-store guest:
make workload-activate ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
make workload-check ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
make workload-stop ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

Use `WORKLOAD=...` to select a declaration. `WORKLOAD_REV` defaults to the host
checkout's current commit and must match the staged source. `WORKLOAD_FLAKE`
selects the staged controller/declaration flake. `WORKLOAD_GENERATION` can select
a retained generation; by default activation selects the latest prepared one
and stop selects the active one, even if a newer generation has been prepared.

Preparation preserves earlier generations. Activation refuses to replace a
running or uncertain generation: explicitly stop it before activation of its
replacement. The guest launches the manifest's command in a transient systemd
user unit with a named rootless Podman container and read-only 9P store. The
activation acknowledgement means the unit was started; `workload-check` separately
checks successful completion and the declared stdout text. Stop confirms both
unit and container termination before releasing exactly that generation's roots.
Prepared but unused generations remain retained; bulk pruning is not implemented.

Guest operations serialize per workload and persist stop markers. Owner intents
and roots survive lost SSH replies. If the guest boot identity changes or a stop
cannot be confirmed, roots remain and the command fails. Automatic reconciliation
after guest reboot is a later gate; do not manually delete uncertain roots.

### One-command CoreOS workload qualification

After updating and staging this checkout, use the existing isolated 9P artifact
state (no disk, Ignition, store reset, or rebuild):

```sh
make workload-qualify ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 \
  SCOPE=nix-xd-arm WORKLOAD=starwisp-probe \
  COREOS_STATE_ROOT="$PWD/.state/coreos-9p-ordering-fixed" \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

This prepares the manifest, then uses the existing Starwisp lifecycle adapter to
archive a stopped prior overlay, boot a fresh guest, qualify Wisp/9P, activate
the prepared workload, check its exit status and `Hello, world!` output, stop it,
release its roots, and stop the guest. A running guest is refused. This target's
VM adapter currently supports ARM64 Podman Machine on macOS; the shared manifest
and owner controller do not contain QEMU architecture-specific behavior.

Evidence includes the resolved manifest, generated guest scripts, journal output,
activation/stop acknowledgements and existing VM qualification records. Per-generation
files are under `<state>/starwisp/workloads/`; they are also copied into the
per-attempt qualification directory. Successful completion includes
`WORKLOAD_QUALIFY_RESULT=passed` and `QUALIFY_STARWISP_RESULT status=passed`.
Smoke integration, persistent application state, concurrent workload qualification,
and remote/GCE transports remain separate work.

### Nested Nix-Alpine inside CoreOS

`WORKLOAD=nix-alpine` uses the same prepare/activate/check/stop interface as the
probe. It runs a pinned Alpine 3.23.0 minirootfs in CoreOS rootless Podman.
Both ARM64 and AMD64 upstream archives are SHA-256 pinned in
`guest/nix-alpine/package.nix`; bootstrap/provider code does not own this workload.
The rootfs archive contains the Alpine base, a `nixuser` account, Nix configuration,
and links to shared store executables. It embeds no Nix store closures.

The executor unpacks only the Alpine rootfs into guest runtime scratch and binds
the existing read-only 9P export at `/nix/store`. It uses a rootless keep-id user
namespace to run UID 1000, a read-only rootfs, no network, and separate writable
tmpfs mounts for `/nix/var`, `/home`, `/run`, and `/tmp`. The UID 1000
entrypoint creates private mode-0700 home and runtime directories on those mounts. It never mounts
the authoritative owner's database or runs the writable-store bootstrap installer.

The qualification registers only runtime-closure metadata in the guest-local
database (using Nix's closure registration format), checks Nix version and native
system evaluation, queries the shared hello closure and executes it, and checks
runtime writes stay on the guest-local mounts. Guest metadata is ephemeral;
builds, downloads, GC and persistent application state are not provided by this
read-only-store workload. No local-overlay store is enabled.

After updating and staging this repository, qualify it with:

```sh
make workload-qualify ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 \
  SCOPE=nix-xd-arm WORKLOAD=nix-alpine \
  COREOS_STATE_ROOT="$PWD/.state/coreos-9p-ordering-fixed" \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

This boots the existing CoreOS artifacts, starts and verifies the actual nested
Nix-Alpine container, then stops it and the VM. It does not leave a persistent
container running. Expected markers include `NESTED_NIX_ALPINE_RESULT=passed`,
`WORKLOAD_QUALIFY_RESULT=passed`, and `QUALIFY_STARWISP_RESULT status=passed`.
CI builds the native x86_64 package, tests its readonly-store execution in a
throwaway chroot, and runs the production executor with real rootless Podman.
That executor test substitutes a read-only local bind for the 9P transport.
These are packaging/runtime checks, not AMD64 CoreOS VM qualification.
ARM64/CoreOS qualification still requires the local command above.


### Managed nested Nix-Alpine environment

`WORKLOAD=nix-alpine-env` is the long-running counterpart to the finite
`nix-alpine` qualification workload. It initializes and checks its guest-local
metadata, then stays alive without an automatic timeout. Its readiness check is
a separate command inside the named container. The workload's rootfs, closure
and source generation remain retained until an acknowledged stop.

After staging the current checkout, use:

```sh
make workload-start ARCH=arm64 PROVIDER=podman MACHINE=coreos-arm64 \
  SCOPE=nix-xd-arm WORKLOAD=nix-alpine-env \
  COREOS_STATE_ROOT="$PWD/.state/coreos-9p-ordering-fixed" \
  COREOS_SSH_KEY="$HOME/.ssh/starwisp-test"
```

Start prepares and retains the generation, starts or reuses the CoreOS VM,
checks Wisp/9P, activates the workload and waits for readiness. It leaves both
the VM and container running. An existing managed VM must match its recorded
container ID, runner digest and SSH port. A stopped legacy qualification VM is
archived once and replaced using the existing disk/ Ignition artifacts. An
unknown running VM or orphaned overlay is refused. Repeated start of the same
generation reuses its running unit/container. A new source generation requires
explicit stop of the previous one before replacement.

Use the same variables with these common post-bootstrap commands:

- `make workload-status`: show recorded owner intent/root retention separately from live guest health (`WORKLOAD_HEALTH`). A successful status query does not mean the workload is healthy.
- `make workload-check`: run the live readiness check again.
- `make workload-shell`: enter `/bin/sh` as UID 1000; exiting leaves the environment running.
- `make workload-stop`: stop the container and unit, then release its generation roots.

Interactive shell content bypasses timestamped command logging. A shell does
not hold the lifecycle lock, so another terminal can stop the environment.
Home, Nix metadata and runtime files are private tmpfs state and disappear at
container stop. This is a running execution environment, not a persistent-data
or writable-store feature.

`workload-stop` leaves CoreOS running, allowing other workloads to use it. After
stopping all workloads, `make coreos-stop` with the same machine/state/profile
variables stops the VM. Do not use VM stop as a substitute for acknowledged
workload stop: uncertain workload roots intentionally remain retained.

The declaration, service controller, status, readiness, shell and stop paths
are shared by both Linux architectures. The composed `workload-start` VM adapter
currently supports ARM64 macOS Podman Machine; native AMD64/CoreOS VM bootstrap
and qualification remain deferred. CI additionally exercises the real running
container, readiness, shell execution and stop with rootless Podman on its
native runner; it substitutes a readonly bind for QEMU's 9P transport.


Store executable symlinks are resolved inside the container at `/nix/store`, not
against CoreOS's `/var/mnt/nixstore` export. Readiness is the execution check;
store-path executability is not probed from the wrong host namespace. An updated
controller can still stop a previously prepared generation safely; only activation
requires matching executor content. Roots remain until the guest acknowledges stop.


### Recreate a running nested Nix-Alpine container

With the managed environment running, `make workload-qualify-recreation` (or
`make workload-recreate`) uses the same architecture/provider/machine/scope,
`WORKLOAD=nix-alpine-env`, CoreOS state root and SSH key as start/status/shell.
It does not boot, stop or replace the CoreOS VM and does not rebuild the workload.

The owner records a recreation transaction against the **active** content
generation, regardless of the most recently prepared generation. It retains
that generation's roots throughout old-instance stop, replacement activation,
readiness and verification. The replacement has a fresh instance ID, unit,
container, runtime directory, home tmpfs and Nix metadata tmpfs. The content
generation, rootfs archive, executable and retained store paths are unchanged.
Per-instance stop markers prevent delayed requests from restarting a retired
instance; delayed cleanup of a legacy instance cannot remove replacement state.

The gate records old/new container IDs and the CoreOS boot ID, marks private
home and metadata state before stop, verifies both markers are absent afterward,
and checks guest-local metadata queries, Nix version and shared executable paths.
It fails unless the container ID changes and the boot/content/store identities
remain unchanged. The replacement is left ready and running, with roots retained.

Expected completion: `WORKLOAD_RECREATE_RESULT=passed`. Evidence is saved under
`<COREOS_STATE_ROOT>/starwisp/workloads/<name>/<generation>/recreations/<transaction>/`
and the usual timestamped host log. Owner state includes both snapshots and the
root fingerprint. Successful shell/status/stop operations select the new instance.

If a guest or owner call is interrupted, retry `make workload-recreate` with the
same configuration to resume the pending transaction. A changed guest boot ID,
missing root or mismatched snapshot fails closed. To abandon a pending recreation,
use `make workload-recreate-abandon`: it acknowledges termination of the current
instance before releasing roots. Ordinary stop/activation is refused while a
recreation is pending. No implicit rollback, bulk root pruning, or cross-boot
reconciliation is performed. Home/database contents are intentionally discarded;
this is not a persistent application-state migration mechanism.

Native CI exercises actual Podman stop/replacement, fresh writable state, metadata
queries and continuous root retention. Local ARM64/CoreOS execution remains the
separate VM qualification gate. Multi-instance concurrency and Smoke integration
follow after that gate passes.

### Six-reader shared-store composition (local qualification)

`compositions.<system>.shared-store-matrix` declares two host readers, two readers
in the existing Starwisp VM, and two readers in a second CoreOS VM. Here “host”
means the Linux Podman Machine on macOS. The existing Nix-Alpine owner remains
the sole writer; these six additional Nix-Alpine containers consume its
`/nix/store` through read-only mounts and have separate tmpfs home, Nix database,
runtime directories, and process namespaces. The owner is infrastructure and is
not counted among the two host readers.

The domain contract also describes VM-local ownership and an independent,
host-owned domain whose allowed readers are only the two VMs. Those domains are
**declarative and not provisioned or qualified yet**. A workload selects one
canonical store domain; changing a domain's reader allowlist does not itself
configure mounts or access controls. Additional domain provisioning must supply
its own backing store, single writer, roots, and export adapter. No experimental
overlay store is needed for the common read-only domain.

Bootstrap remains Bash-only. Composition phases require host Python 3.9 or newer
using only its standard library; `PYTHON=/path/to/python3` selects the interpreter.
The owner-side controller and validator use Python supplied by the locked Nix
flake. Make is the public interface; no separate Python CLI is required.

Run each phase from the same committed and staged revision:

```sh
make composition-plan
make composition-prepare
make composition-start
make composition-qualify
make composition-status
# Later, stop only these six readers; leave both VMs and the owner running:
make composition-stop
```

Use the same `ARCH`, `PROVIDER`, `MACHINE`, `SCOPE`, `COREOS_STATE_ROOT`, and
`COREOS_SSH_KEY` settings as the qualified ARM environment. The primary state
must already contain the qualified Starwisp base image and Ignition. VM2 gets a
separate writable QCOW overlay, SSH port 2223, and container
`coreos-store-matrix-vm2`; it shares immutable boot artifacts without copying the
Nix store. Existing `nix-alpine-env` sessions are outside this composition.
The current VM launcher is macOS ARM64; both architecture outputs expose the
same declarations, while native x86 VM qualification remains deferred.

The gate writes identical marker filenames with different reader values in each
private state directory, verifies all six after every reader has written them,
and checks common Nix/package paths, distinct container/process namespaces, and
three distinct kernel boot identities. For one reader on each placement it
pauses recreation after confirmed stop, checks the other five remain healthy
and rooted, resumes replacement, then checks normal stop/start isolation.
Generation roots remain retained while replacement is pending. The gate leaves
all six readers running and records evidence below `.state/compositions/`.
Each phase authenticates the staged revision, and preparation/start/qualification
check the workload source, architecture, domain, and placement against the plan.
Starting a new preparation, start, qualification, or stop invalidates the prior
qualification result. A successful gate atomically records the final six-reader
snapshots in `qualification.json`; runtime command failures retain their output
in the normal scope-specific Make log.

Phases are intentionally independent for sandbox CI/CD. On interruption, finish
or abandon a pending recreation with the existing lifecycle before changing the
pinned plan. `composition-stop` abandons pending recreation and stops active
composition readers; it does not destroy VMs or store volumes. Prepared-only
roots remain retained. A guest reboot or changed owner boot identity fails
closed rather than silently releasing roots; fresh sandbox provisioning is an
acceptable recovery path. GCE/spot restart reconciliation and Smoke runtime
credentials remain separate subsequent gates. Run this topology locally;
contract tests do not establish CoreOS runtime qualification.

For one shareable log of the entire local sequence, use
`make composition-local` with the same architecture, provider, machine, scope,
CoreOS state, and SSH-key settings. It runs static checks, stages the committed
checkout, and runs plan, prepare, start, qualify, and status serially, stopping
at the first failure. The complete stdout/stderr is saved to
`logs/<scope>-composition-local-<UTC>-<pid>.log`; individual phase logs remain
available too. Static checks also have their own log when run independently.

Isolation checkpoints batch script generation and root verification in the owner,
then check both readers through one connection per placement. At most three
placements run concurrently. Every write round completes before its check round;
stop/recreation acknowledgements remain ordered. The controller executable is
built and retained through a per-source Nix out-link once per phase, then invoked
directly without repeated `nix run`. Probe rounds and lifecycle actions report
elapsed time. Per-placement output is retained in numbered `probe-*.log` files,
with reader identities and timing summaries in the combined Make log.

To replace an interrupted sandbox run, press Ctrl-C and wait for Make to exit.
After updating the host checkout, run `composition-stop` **before staging the
new revision**, then `composition-local`. Stop accepts the previous plan and
staged revision for cleanup, retains roots until termination is acknowledged,
and leaves both VMs, the store owner, and unrelated workloads running. Other
phases continue requiring the selected committed and staged revision to match.

If the old terminal is still running and `composition-stop` reports a busy lock,
use `make composition-cancel`, followed by `composition-stop` and
`composition-local`. Cancellation uses host `lsof` and `ps` to identify the
controller with this composition lock open, verifies its command, and terminates
only that controller and its local transport descendants. It does not release
roots or stop guest services; the managed stop phase still acknowledges their
termination. Never delete a busy lock file: removing its pathname does not
terminate the holder and could permit overlapping controllers.

### Profile existing shared-store readers

`make composition-profile` measures the existing composition without staging a
new source, preparing outputs, restarting readers, or invalidating its passed
qualification. It uses the previous resolved plan and staged controller after a
host checkout update. One reader per placement is sampled serially to avoid
benchmark contention. `PROFILE_SAMPLES=1` is the default; select 2 or 3 for
repeated warm measurements. No caches are dropped, so these are observations of
the running environment rather than cold-start benchmarks.

The logged layers are connection round-trip, native shell baseline, Podman
inspection, Alpine exec/shell, shared-store Hello, Nix version, normal Nix path
query, and offline Nix path query. Each command is bounded to 60 seconds (plus
up to 5 seconds for forced termination); nonzero exits/timeouts are reported,
not treated as successful timings. Comparisons include Podman exec overhead;
they do not isolate raw filesystem latency. The offline comparison tests the
network-detection hypothesis without changing Nix configuration. Profiling
checks reader identity/boot and all six root fingerprints and leaves guest
services running. Local Nix queries use each reader's existing private metadata.

Send the printed `logs/<scope>-composition-profile-<UTC>-<pid>.log` file for
review. Structured timings and placement output are also saved in
`.state/compositions/<scope>/<composition>/profile.json` and `profile-*.log`.
Do not run `composition-local` just to profile an already qualified topology.
