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
