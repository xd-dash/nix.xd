# nix.xd

Generic host-side entry point for [dash-xd/nix-alpine](https://github.com/dash-xd/nix-alpine).
This repository owns the cross-architecture Nix interface and the macOS ARM
bootstrap adapters. It does not own application compositions or qualification
modules; those belong to application repositories such as Agni.

## Platform and execution model

| Host | Linux workload | Execution interface |
| --- | --- | --- |
| x86_64 Linux | x86_64-linux | pinned Nix-Alpine `local/Makefile`, rootless Podman/systemd |
| aarch64 Linux | aarch64-linux | pinned Nix-Alpine `local/Makefile`, rootless Podman/systemd |
| Apple Silicon macOS | aarch64-linux | `nix.xd` generic Make adapter, Apple `container` or Podman Machine |

The top-level `flake.nix` exports the same `nix-xd` app on
`x86_64-linux`, `aarch64-linux`, and `aarch64-darwin`.
The app selects the native host adapter and Linux execution architecture.
It pins Nix-Alpine to
`037290d6713cb5efc548982c42b26f77f467e58a`
(from `codex/nixxd-refresh-reset`) and uses that checkout's original
Makefile on native Linux. The input hash is retained in `flake.lock`.

The macOS Make adapter is deliberately separate while Apple Container
qualification is being developed; it is not a copy of the Linux Podman
host-runtime tester. The Make interface is the convenience layer, not
application logic. Agni does not need a Makefile.

## Apple Silicon: use the existing runtime

From macOS, not from inside the `nix-xd-arm` shell:

```sh
cd ~/workspace/nix.xd
git fetch origin
git switch --track origin/codex/nix-alpine-cross-arch-contract
make check-static
make smoke PROVIDER=container SCOPE=nix-xd-arm
```

If already on the branch, use `git pull --ff-only` instead of `git switch`.
`make smoke` is non-destructive. It does not recreate the container, image,
or persistent `/nix` volume.

To synchronize and stage the pinned Nix-Alpine toolbox source:

```sh
make sync REPO=dash-xd/nix-alpine \
  BRANCH=codex/nixxd-refresh-reset \
  REV=037290d6713cb5efc548982c42b26f77f467e58a \
  SYNC_NAME=nix-alpine/nix-alpine

make stage PROVIDER=container CHECKOUT=nix-alpine/nix-alpine
make show PROVIDER=container FLAKE=nix-alpine/nix-alpine/toolbox
```

All three operations emit UTC timestamped logs in `logs/`. The log wrapper
streams output and returns the real exit code, including on failure.
Override the output location with `NIX_XD_LOG_DIR`. The `stage` operation
uses `git archive HEAD`, excludes untracked files and Git metadata, and
initializes `/workspaces` safely in existing containers as needed.

### Bootstrap providers

```sh
make bootstrap                     # Podman Machine + Quadlet (default)
make bootstrap PROVIDER=container  # Apple native container, no Podman Machine
```

The Apple `container` provider runs Linux in per-container micro-VMs and
keeps its writable `/nix` volume independent from Podman. Its existing,
verified matching container is reused without a second volume attachment.
Neither provider installs an application checkout. The macOS host does not
need Nix installed for the Make path.

For users who already have Nix installed on macOS, the top-level flake
provides a separate `nix run` entry point. The flake doesn't install Nix
on the macOS host.

## Generic Nix commands

```sh
make show FLAKE=compositions/example TARGET='#output' PROVIDER=container
make check FLAKE=compositions/example PROVIDER=container
make build FLAKE=compositions/example TARGET='#package' PROVIDER=container
make run FLAKE=compositions/example TARGET='#app' PROVIDER=container
```

These commands execute *inside* Nix-Alpine. `make image-build` is the
separate operation for building the Nix-Alpine OCI image.

Application sources live under `WORKSPACES`, with `nix-alpine/` and
`compositions/` as sibling directories. Mac workspaces are explicitly
staged at the same `/workspaces` path used by the native-Linux toolbox.
No broad host directory or container-engine socket is mounted into the
Apple runner.

## Qualification-plan contract

The schema is owned by the caller's plan app, not by `nix.xd`.
Nix-Alpine's `local/PLAN_INTERFACE.md` defines `schemaVersion: 2`,
`protocolVersion: 1`, stable module IDs, dependencies, phases, inputs,
outputs, and cleanup. The app resolves and executes these modules.

On either backend, the standard selection vocabulary is:

```sh
make qualify-plan PROVIDER=container \
  PLAN_REPO=owner/repository \
  PLAN_BRANCH=branch \
  PLAN_REV=<40-character-Git-SHA> \
  PLAN_CHECKOUT=compositions/example \
  PLAN_FILE=plan/qualification.json \
  PLAN_FLAKE=plan \
  PLAN_TARGET=qualify-plan \
  PLAN_GATE=all \
  PLAN_CAPABILITIES=nix-exec
```

On Apple Container, only `PLAN_CAPABILITIES=nix-exec` is accepted.
It transports the same `--plan`, `--gate`, `--workspaces`, `--toolbox`,
`--nix-alpine-local`, `--scope`, and `--plan-checkout` arguments to
the application flake app. The application must validate module protocol
versions and enforce requirements for its own modules. This is *not*
a claim that a CoreOS VM or Fatline service is qualified.

The Linux Nix-Alpine plan runner provides disposable host Podman/systemd
qualification and is selected directly by the unified flake entry point.
Apple Container has no host Podman socket, Linux user-systemd bus, or
nested KVM. Plans requesting those runtime capabilities fail closed
rather than reporting false success. For now the Apple adapter also
rejects `PLAN_SOURCES`, `PLAN_ARTIFACT_MANIFEST`, and `RETAIN=1`;
these x86 plan features are not yet implemented there.

## Qualification and limits

- `make check-static` and GitHub CI validate syntax and Make argument contracts.
- `make smoke PROVIDER=container` is the next Mac runtime gate; its output
  must be reviewed before considering the Apple provider qualified.
- The current OCI image installs Nix 2.31.2 in ARM Alpine Linux. It does not
  install Nix on macOS.
- Existing containers and persistent store volumes are preserved.
- Pinning the Nix-Alpine source does not guarantee reproducibility of network
  downloads performed by its image build.
- QEMU/CoreOS/Farcaster provisioning and optional Fatline compositions remain
  the responsibility of the application repository, not `nix.xd`.
