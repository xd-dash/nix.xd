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
