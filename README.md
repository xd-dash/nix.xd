# nix.xd

A small host installer for a rootless Podman + systemd/Quadlet Nix-Alpine service.
This does not install NixOS or change host packages.

| Host | Build context |
| --- | --- |
| x86_64 Linux | Exact flake input from dash-xd/nix-alpine |
| ARM64 Linux (aarch64) | arm/ in this repository |

The x86_64 input is pinned to upstream main at 80a2821b7571edd09507f9b4349e2f1ed3daf900.
No changes to nix-alpine are required. Developing branches are deliberately excluded.
Only the build-context adapter should need adjustment when upstream settles.


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
