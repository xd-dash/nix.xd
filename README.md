# nix.xd — cross-platform Nix-Alpine entry point

**Standard provider: rootless Podman with systemd Quadlets.**

The Mac uses Podman Machine as its Linux host. `nix.xd` selects the
machine, synchronizes a pinned Nix-Alpine checkout, and delegates the actual
bootstrap to **`dash-xd/nix-alpine/local/bootstrap.sh` running inside that
machine**. Linux and macOS therefore use the same Quadlet, keep-id user
namespace, persistent Nix volume, mounted workspace, and source refresh
contract. Smoke and other applications own their tool compositions and tests.

## Ownership and mount topology

```text
macOS: ~/workspace/nix.xd
  └── Podman Machine (ARM Linux, rootless user systemd)
        └── nix-xd-smoke-podman.service (canonical Nix-Alpine Quadlet)
              /workspaces  ↔ macOS nix.xd checkout (read/write)
              /nix         ↔ named volume nix-xd-smoke-podman-store
              nixuser      ↔ VM rootless user, UserNS=keep-id:uid=1000,gid=1000
              /workspaces/compositions/smoke  → Smoke Git checkout
              /workspaces/.smoke-state        → Smoke binary and Go environment
              /workspaces/.cache/nix          → optional shared file binary cache
```

The one Nix store is writable only by its scoped service. A second Nix-Alpine
runner gets **its own named Nix volume**. It can see the same mounted source
tree and import exact store closures from the workspace file cache. Do **not**
attach a live writable /nix volume to two independent Nix processes.

## Mac: first-time canonical Podman bootstrap

All commands run **on macOS**. No host Nix or host Go installation is required.
Podman must already be installed, and the Podman Machine must be based on Linux
with a working rootless user systemd manager. The normal macOS `/Users`
share must be accessible in the VM.

```bash
cd ~/workspace/nix.xd
git fetch origin
git switch codex/podman-unified-bootstrap
git pull --ff-only

make check-static
make inventory MACHINE=podman-machine-default
make bootstrap PROVIDER=podman MACHINE=podman-machine-default \
  SCOPE=nix-xd-smoke-podman
make workspace-check PROVIDER=podman MACHINE=podman-machine-default \
  SCOPE=nix-xd-smoke-podman
```

Bootstrap creates a **new** service and a **new** persistent volume, and
does not stop or delete any existing Apple Container runner. If the machine
already exists it is reused. The pinned Nix-Alpine revision is in both
`Makefile` and `flake.lock`; updating that pin is an explicit repository
change, not an implicit branch-head upgrade.

`make refresh PROVIDER=podman SCOPE=nix-xd-smoke-podman` reuses the exact
pinned checkout, rebuilds the image and restarts the canonical systemd service
without resetting its Nix store. Update `nix.xd` with `git pull --ff-only`
before running refresh to adopt a newly reviewed pin.

## Smoke as the caller-owned tool workspace

```bash
make sync REPO=xd-dash/smoke BRANCH=codex/arm-smoke-shared-workspace \
  SYNC_NAME=compositions/smoke SCOPE=nix-xd-smoke-podman

make exec PROVIDER=podman SCOPE=nix-xd-smoke-podman \
  CMD='nix develop /workspaces/nix-alpine/nix-alpine/toolbox#go -c bash /workspaces/compositions/smoke/tools/nix-alpine.sh refresh-test'

make exec PROVIDER=podman SCOPE=nix-xd-smoke-podman \
  CMD='nix develop /workspaces/nix-alpine/nix-alpine/toolbox#go -c bash /workspaces/compositions/smoke/tools/nix-alpine.sh vet'

make exec PROVIDER=podman SCOPE=nix-xd-smoke-podman \
  CMD='nix develop /workspaces/nix-alpine/nix-alpine/toolbox#go -c bash /workspaces/compositions/smoke/tools/nix-alpine.sh build'

make exec PROVIDER=podman SCOPE=nix-xd-smoke-podman \
  CMD='nix develop /workspaces/nix-alpine/nix-alpine/toolbox#go -c bash /workspaces/compositions/smoke/tools/nix-alpine.sh commands'
```

Smoke's `tools/nix-alpine.sh` uses a shared, mutable
`/workspaces/.smoke-state` directory under Podman. Its installed binary
is replaced atomically; its Go environment and composition state remain
owned by Smoke. `nix.xd` does not parse or execute application module
graphs. Go tests, vet, self-composition and environment mutation are Smoke's
responsibility; Nix-Alpine provides the pinned Go toolchain.

## One-command evidence collection

Once a Smoke checkout is present under `compositions/smoke`, run
`make qualify-smoke PROVIDER=podman MACHINE=podman-machine-default
SCOPE=nix-xd-smoke-podman`. This is the **single** command for the Mac
qualification, including source refresh, complete Go test suite, vet, binary
build, shared-workspace identity, UID/GID checks, canonical Quadlet refresh,
and verification that the named Nix store, Nix profile closure and Smoke
binary persist.

The target records `GATE=<name> START/PASS`, `PERSISTENCE_BEFORE`,
`PERSISTENCE_AFTER`, and a terminal `QUALIFICATION_RESULT=PASS|FAIL`.
`bin/nix-xd-log` writes the exact exit status into the diagnostic file.
Upload `logs/nix-xd-smoke-podman-qualify-smoke-*.log` for review; do not
manually interpret partial command output or delete old stores. The
qualification intentionally performs a full pinned bootstrap refresh and
may fetch build dependencies. It does **not** remove the previous Apple
Container instances or volumes.

## Other flakes and a second container

```bash
make show PROVIDER=podman SCOPE=nix-xd-smoke-podman FLAKE=tests/plan-fixture
make check PROVIDER=podman SCOPE=nix-xd-smoke-podman FLAKE=tests/plan-fixture
make build PROVIDER=podman SCOPE=nix-xd-smoke-podman FLAKE=path TARGET='#package'
make run PROVIDER=podman SCOPE=nix-xd-smoke-podman FLAKE=path TARGET='#app'
```

To run another isolated Nix-Alpine with the same workspace but a different
persistent store, bootstrap a **different `SCOPE`**, e.g.
`SCOPE=nix-xd-smoke-reader`. The canonical Quadlet currently makes the
workspace read-write for both; **enforce a single Smoke mutation owner**.
A hard read-only second-container mount is not yet qualified. Export/import
closures with `make store-export` and `make store-import` using
`STORE_PATH=/nix/store/<exact-path>`, which publish to and read from
`/workspaces/.cache/nix`. Only import from a trusted local producer because
the local cache import deliberately uses `--no-check-sigs`.

## Migration and cleanup safety

Run `make inventory` **before** cleanup. It only reports resource state:
Podman machines, scoped Quadlets, Podman images/containers/volumes, and
legacy Apple Container instances/volumes. Confirm new Podman bootstrap,
workspace identity, Smoke tests, persistent store reuse across refresh,
and any necessary Nix closure exports **before** stopping the old runtimes.

The legacy Apple provider remains in this branch for explicit rollback
(`PROVIDER=container`), but it is not the recommended path. Neither
bootstrap nor refresh removes an Apple container, Apple volume, Podman
machine, or another scope's Quadlet. Deleting an old store is a separate,
irreversible operation requiring an exact resource inventory and explicit
approval; there is deliberately no wildcard `make clean`.

## Current qualification limits

GitHub Actions checks the cross-platform flake pin, shell syntax, mock
provider boundaries, and Podman bootstrap delegation. The actual Apple
Silicon Podman Machine, VirtioFS host path permissions, Nix-Alpine Quadlet
service, Smoke workspace mutation, and image build must still be verified
from macOS.

The canonical Dockerfile currently uses an unpinned `alpine:latest` base
and downloads a Nix installer from upstream. Reproducible source selection
is pinned at Git SHA and flake lock, but a fully content-pinned OCI bootstrap
remains additional supply-chain hardening.
