# Agni-owned CoreOS plan transition

This is a transitional runtime adapter, not a completed transfer of Fatline lifecycle logic out of `nix.xd`.

Agni `v20261111` owns `local/fatline/coreos/plan.nix`. Its `flake.lock` pins both nixpkgs and the Nix-Alpine runtime. The Nix-Alpine owner builds `#coreos-plan-vm1`; the host's generic VM transport still performs guest operations.

The CoreOS VM starter, host-link controller, adapter refresh, and service selector consume the **same** Agni plan. They no longer evaluate `nix.xd#fatlinePlans`. The old flake output and old test fixture are retained until the new runtime path passes live qualification.

## Preflight on the Mac

From a local, dated controller checkout:

```sh
cd "$HOME/workspace/nix.xd20261111"
git pull --ff-only
make check-static

cd "$HOME/workspace/agni20261111"
git pull --ff-only
COMPOSITION_REV="$(git rev-parse HEAD)"

cd "$HOME/workspace/nix.xd20261111"
WORKLOAD_REV="$(git rev-parse HEAD)"

make stage PROVIDER=podman SCOPE=nix-xd-arm \
  WORKSPACES="$HOME/workspace" CHECKOUT=agni20261111

make stage PROVIDER=podman SCOPE=nix-xd-arm \
  WORKSPACES="$HOME/workspace" CHECKOUT=nix.xd20261111

make agni-coreos-plan-check PROVIDER=podman SCOPE=nix-xd-arm \
  COMPOSITION_FLAKE=/workspaces/agni20261111/local/fatline \
  COMPOSITION_REV="$COMPOSITION_REV" FATLINE_PROFILE=vm1
```

The plan command is read-only with respect to the guest. It will build the plan JSON in Nix-Alpine and write `.state/agni-coreos/vm1-selection.json` with immutable evidence. The controller rejects a staged Agni checkout whose SHA differs from `COMPOSITION_REV`, a missing lock entry, or a changing lock. It uses `nix build --no-update-lock-file` so missing locked dependencies cannot be resolved opportunistically.

The next conditional integration command (after the preflight passes and a disposable CoreOS VM1 is intended) is:

```sh
make fatline-vm-local PROVIDER=podman ARCH=arm64 SCOPE=nix-xd-arm \
  WORKLOAD_FLAKE=/workspaces/nix.xd20261111 WORKLOAD_REV="$WORKLOAD_REV" \
  COMPOSITION_FLAKE=/workspaces/agni20261111/local/fatline COMPOSITION_REV="$COMPOSITION_REV" \
  FATLINE_PROFILE=vm1
```

The composed lifecycle remains a legacy `make fatline-vm-local` adapter until the Agni-owned orchestration app can replace it; this operation **will** start/mutate the CoreOS guest and Fatline services. The qualification must inspect boot ID, `systemctl --user` service state, readiness, Redis ACL isolation, Logma/Skymill integration, crash recovery, and generation roots. Do not equate a successful plan check with guest qualification.

Old Fatline state without the new immutable composition manifest is rejected; make a deliberate fresh-sandbox selection or migration rather than overwriting it. No existing runtime or GC roots are automatically removed.

## Ownership

- Agni: the source graph and service/deployment artifacts.
- Nix-Alpine: immutable flake evaluation, builds, and closure ownership.
- nix.xd: staging and generic host-to-guest runtime transport.
- Thin Makefile: dispatch and qualification gates.

After VM1 qualifies, move the remaining Fatline-specific phase graph into Agni's orchestration app and retire the old `fatlinePlans`, controllers, and fixture only after confirming no other active callers.

## Persistent CoreOS VM state and fresh bootstrap

CoreOS state defaults to `$HOME/.local/state/nix-xd/coreos`, shared by dated source checkouts. The host launcher, SSH readiness helper, Makefile, and composition runtime agree on this default. `COREOS_STATE_ROOT` remains an explicit override. The state directory contains base and overlay qcow2 disks, Ignition, boot manifests and SSH evidence. It is not source code and is never deleted by daily workspace cleanup.

If no previously prepared `starwisp/build.txt` exists, the VM cannot start merely because the Agni plan qualifies. From the dated `nix.xd` checkout, after staging Agni (including its `qemu/coreos-live/local` flake), provision the disposable VM artifacts **once**:

```sh
make coreos-container-build PROVIDER=podman SCOPE=nix-xd-arm \
  COREOS_FLAKE=/workspaces/agni20261111/qemu/coreos-live/local \
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store

make coreos-ignition-build PROVIDER=podman SCOPE=nix-xd-arm \
  COREOS_FLAKE=/workspaces/agni20261111/qemu/coreos-live/local \
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store \
  COREOS_SSH_PUBLIC_KEY="$HOME/.ssh/starwisp-test.pub"

make coreos-preflight PROVIDER=podman SCOPE=nix-xd-arm \
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store
```

The QEMU runner and Fedora CoreOS QCOW2 may require substantial downloads. The Ignition step requires an existing SSH public key; it is not created automatically. If an existing VM is still running with its disk mounted elsewhere, first reconcile that VM identity rather than constructing another overlay against its base.

After preflight succeeds, run `fatline-vm-local` with the same state root (now default), `COREOS_NIX_STORE_VOLUME=nix-xd-arm-store`, and immutable Agni/Controller revisions. A missing or unqualified VM runner must fail before guest activation.

Do not copy a live overlay between workspaces. Prefer a persistent state root; source checkout rotation must never relocate guest state.

## Probe-only readiness correction on an active VM

The original Agni activation plan may remain pinned at its validated revision while a corrected qualification probe is evaluated separately. Use the optional `FATLINE_PROBE_REV=<40-hex-commit>` on `fatline-services-probe-refresh` only. This fetches the exact candidate Agni revision, builds its `coreos-services-vm1` bundle, verifies that Logma, Skymill, and Ratelimiter component revisions are unchanged, retains the candidate closure, and persists the qualification probe source. It does **not** rebind running application binaries, regenerate Quadlets, or restart Redis.

Subsequent `fatline-services-qualify` uses the persisted probe executable, even when the override is omitted. A failed qualification stays unqualified. Do not change `COMPOSITION_REV` from the active machine-plan revision during this operation; the host controller still requires exact existing provenance.

The Logma `/lifecycle/readyz` endpoint returns an authenticated plain-text `ready` response, not JSON. The probe validates HTTP 200 and the plain-text readiness contract, while Skymill message/delivery endpoints continue using JSON decoding. After qualification, promote the corrected probe revision into a new Agni machine plan through an explicit composition migration, not by silently changing an active plan.

## Composition-owned Smoke host artifact (transitional)

The currently running VM1 keeps the selected composition revision `5442e5f9b13479edefb55cfa3c3cd518e199ad5c` and its provisioned application binaries. Do not rebind the active plan to test the host tool.

Agni now exposes `#smoke-host-artifact`, which executes inside the Nix-Alpine owner, fetches the exact Smoke source revision through Nix, cross-compiles the `cmd/smoke-wisp` Go entry point for `darwin/arm64`, adds the executable to the owner's Nix store, and installs a stable GC root. This is an **explicitly effectful Nix app** rather than a hermetic derivation: module downloads happen at runtime under the pinned `go.mod`/`go.sum`, and the Nix owner reports the resulting SHA-256. Do not claim binary reproducibility until a fixed-output vendoring derivation is qualified.

The generic `composition_artifact` exporter copies the exact store file through the configured Podman machine connection, checks the SHA-256 before atomic publication, and produces provenance evidence. The Fatline application gate requests this dependency automatically; no separate `wisp-go-build` target or manually synchronized `WISP_SMOKE_REV` is needed.

Older VM1 plans predate the `hostArtifacts` field. Their Agni-owned host action explicitly selects an immutable Smoke artifact while preserving the original running composition identity. The generic entry point below replaces the former literal Fatline Make target.

## Generic project-host-run selection

Application-specific resource commands no longer need a Make target. Run `make project-host-run PROJECT=<checkout> APPLICATION=<app> ACTION=<action>`. The generic runtime checks the local project's exact Git HEAD and clean tracked files, selects `local/<app>/host-actions/<action>.sh`, and executes the project-owned host action with the selected infrastructure environment. The project script owns its side effects.

For the already-running Fatline VM1 (legacy pinned composition), use the Agni project's resource action with the active composition revision:

```sh
make project-host-run PROJECT=agni20261111 APPLICATION=fatline ACTION=resource-qualify \
  PROVIDER=podman ARCH=arm64 SCOPE=nix-xd-arm \
  COREOS_STATE_ROOT="$HOME/.local/state/nix-xd/coreos" \
  COREOS_NIX_STORE_VOLUME=nix-xd-arm-store COREOS_SSH_KEY="$HOME/.ssh/starwisp-test" \
  WORKLOAD_FLAKE=/workspaces/nix.xd20261111 WORKLOAD_REV="$(git rev-parse HEAD)" \
  COMPOSITION_FLAKE=/workspaces/agni20261111/local/fatline \
  COMPOSITION_REV=5442e5f9b13479edefb55cfa3c3cd518e199ad5c FATLINE_PROFILE=vm1
```

The host action selects the exact Smoke artifact flake itself; there is no manual Smoke build or `ARTIFACT_FLAKE` argument. The legacy Fatline-specific Python code remains temporarily in `nix.xd`; the generic dispatcher has no application-specific names or operation mapping. The old literal `fatline-resource-logmash-qualify` target is removed.
