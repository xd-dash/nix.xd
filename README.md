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


## Generic Make interface (macOS Apple Silicon)

The Makefile accepts `PROVIDER=podman|container`, defaulting to `podman`.
The shared ARM image is defined in `arm/Dockerfile`; providers only manage
host preparation, runtime storage and lifecycle. Neither provider runs Agni,
CoreOS, QEMU or Wisp as part of bootstrap.

```sh
mkdir -p ~/workspace
git clone https://github.com/xd-dash/nix.xd.git ~/workspace/nix.xd
cd ~/workspace/nix.xd

make bootstrap                      # Podman Machine (default), rootless Quadlet
make bootstrap PROVIDER=container   # Apple native container, no Podman Machine
make status PROVIDER=container
make shell PROVIDER=container
```

### Providers

- **Podman (default):** On macOS, installs the Podman CLI with Homebrew when
  absent, initializes/starts an Apple Hypervisor-backed Linux ARM64 VM, builds
  the OCI image, and installs the rootless systemd user Quadlet in that VM.
  Its existing bootstrap remains at `arm/bootstrap-podman.sh`.
- **Apple container:** Requires Apple Silicon with macOS 26 or newer. Installs
  the `container` Homebrew formula if absent, initializes the native container
  services and recommended Linux kernel if needed, builds the same ARM64 OCI
  image, and runs Nix-Alpine in a lightweight per-container VM. It uses **no
  Podman Machine, no Linux host Quadlet and no persistent systemd user manager**.
  A named Linux volume persists `/nix`; on first use it is seeded from the
  image's installed Nix store. It does not auto-start at macOS login.
  The Apple provider may require an initial interactive system/kernel setup.

All provider-specific implementation is in `arm/bootstrap-*.sh` and
`bin/nix-xd-container`. The public Make targets are: `bootstrap`, `plan`,
`machine-start`, `machine-stop`, `build`, `start`, `stop`, `restart`,
`status`, `logs`, `shell`, `exec`, `run`, `sync`, `compose`, and `check`.
The `machine-start`/`machine-stop` targets refer to container-system services
with the Apple provider; `machine-stop` stops **all** of Apple's container
services, not just this runner. Prefer `make stop PROVIDER=container` when
stopping only Nix-Alpine.

Use the same provider on subsequent commands, for example:

```sh
make start PROVIDER=container
make exec PROVIDER=container CMD='nix --version'
make compose PROVIDER=container WORKSPACE="$HOME/workspace/agni" \
  COMPOSE_CMD='nix shell nixpkgs#go --command go test ./...'
```

Application source is copied into `/home/nixuser/workspace`, not mounted
from the host. `sync` includes hidden files and Git metadata, so only copy
trusted directories without secrets. The caller controls the application
command, dependencies and artifacts; **Agni owns the QEMU/CoreOS/Wisp logic**.
The current Agni QEMU workflow is not yet ARM-qualified.

The two providers have separate image stores and container state even when
their scopes have the same name. `make build` alone does not replace a
previously created runtime container; bootstraps intentionally preserve
existing containers and volumes rather than silently destroying them.
Only one writer should access a given Nix store at a time.

`make check` validates script syntax and Make expansion for both providers,
but does not boot the Mac runtime or certify a Nix build.

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
