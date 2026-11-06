# nix.xd

A cross-platform host entry point for Nix-Alpine. Its primary interface is
**mount a source workspace and execute a caller-owned Nix flake**.

- `nix.xd`: provider selection, bootstrap, workspace mount, generic Nix command dispatch.
- `dash-xd/nix-alpine`: persistent containerized Nix execution and store.
- Application flakes (including Agni): builds, tests, services, qualification,
  dependencies, cleanup and evidence.
- GitHub Actions: automate the same commands on appropriate runner hosts.

Neither `nix.xd` nor Nix-Alpine needs application-specific plan/module knowledge
to build, run or check a flake. The synthetic schema-v2 plan fixture remains an
optional demonstration of application-owned qualification logic.

## Host and guest architecture

| Host | Linux execution system | Provider |
| --- | --- | --- |
| x86_64 Linux | x86_64-linux | Rootless Podman with systemd |
| aarch64 Linux | aarch64-linux | Rootless Podman with systemd |
| Apple Silicon macOS | aarch64-linux | Apple `container` or Podman Machine |

`flake.nix` exposes an `nix-xd` app for all three hosts, with the
generic Nix-Alpine input pinned by `flake.lock`. The native Linux flake
entry point delegates to the pinned Nix-Alpine Make adapter.

## Apple Container: mount and execute

Run from **macOS**, not inside the Linux container. Use a NEW scope for the
first bind-mount qualification so the existing `nix-xd-arm` container and
`nix-xd-arm-store` volume stay untouched.

```bash
cd ~/workspace/nix.xd
git switch codex/nix-alpine-cross-arch-contract
git pull --ff-only

make bootstrap PROVIDER=container SCOPE=nix-xd-bind WORKSPACE_MODE=bind
make workspace-check PROVIDER=container SCOPE=nix-xd-bind
make show PROVIDER=container SCOPE=nix-xd-bind FLAKE=tests/plan-fixture
make check PROVIDER=container SCOPE=nix-xd-bind FLAKE=tests/plan-fixture
```

The new runner mounts:

```text
Host WORKSPACES (default: ~/workspace/nix.xd)
           => /workspaces  (read-only live bind mount)
Named volume nix-xd-bind-store
           => /nix         (persistent, writable)
```

Host checkout updates appear directly under `/workspaces`; there is no
`make stage` step. The workspace is read-only in the guest, while the Nix
store remains writable by the unprivileged Nix user. Restrict the host
workspace directory to source material appropriate for the guest to read.

Apple Container supports bind mounts at container creation. **Existing
containers cannot be retrofitted with mounts**: an existing scope that lacks
a valid read-only workspace mount fails closed rather than silently falling
back to a copy. Bootstrap never automatically deletes or replaces the legacy
runner or store.

A new `SCOPE` creates its own persistent store. The first flake run may
fetch binary-cache dependencies again; these are not shared with the
legacy `nix-xd-arm-store` volume.

## Generic flake interface

```bash
make show  PROVIDER=container SCOPE=nix-xd-bind FLAKE=compositions/agni
make check PROVIDER=container SCOPE=nix-xd-bind FLAKE=compositions/agni
make build PROVIDER=container SCOPE=nix-xd-bind FLAKE=compositions/agni TARGET='#image'
make run   PROVIDER=container SCOPE=nix-xd-bind FLAKE=compositions/agni TARGET='#qualify'
```

These invoke Nix inside Nix-Alpine against the **live mounted source tree**.
The `ARGS` variable passes space-separated application arguments after
`--`; use a flake app with an explicit CLI for more complex input.
The application flake validates any external runtime dependencies. It can
use a richer qualification protocol without requiring Nix-Alpine to parse it.

`make sync REPO=owner/repo ...` remains a host-side convenience for checking
out exact Git sources into `WORKSPACES`. It is **not required** for local
flakes. `make stage WORKSPACE_MODE=staged` remains for explicitly selected
legacy snapshot runners and is not used by bind mode.

## Logging, qualification, and boundaries

`make bootstrap`, `workspace-check`, `show`, `check`, `build`, and `run`
stream output and write timestamped logs under `logs/`. The wrapper reports
the result and preserves the actual command exit status. Set
`NIX_XD_LOG_DIR` to override the destination.

`make workspace-check` compares the host and guest SHA-256 digest of
`flake.nix` and checks that `/workspaces` is read-only and `/nix` is
writable. This verifies a live mounted source and persistent store access.

The Mac provider does not expose the host's Linux user-systemd bus,
Podman socket, or KVM. A caller-owned flake that requires these interfaces
must check them or run on a suitable host. A successful Nix build is **not**
evidence of successful CoreOS boot or Fatline lifecycle qualification.

The current Alpine image and Nix installer have upstream network inputs not
fully locked by content digest. Source flakes should commit `flake.lock`.
