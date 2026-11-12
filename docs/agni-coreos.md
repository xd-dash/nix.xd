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
AGNI_REV="$(git rev-parse HEAD)"

cd "$HOME/workspace/nix.xd20261111"
WORKLOAD_REV="$(git rev-parse HEAD)"

make stage PROVIDER=podman SCOPE=nix-xd-arm \
  WORKSPACES="$HOME/workspace" CHECKOUT=agni20261111

make stage PROVIDER=podman SCOPE=nix-xd-arm \
  WORKSPACES="$HOME/workspace" CHECKOUT=nix.xd20261111

make agni-coreos-plan-check PROVIDER=podman SCOPE=nix-xd-arm \
  AGNI_FLAKE=/workspaces/agni20261111/local/fatline \
  AGNI_REV="$AGNI_REV" FATLINE_PROFILE=vm1
```

The plan command is read-only with respect to the guest. It will build the plan JSON in Nix-Alpine and write `.state/agni-coreos/vm1-selection.json` with immutable evidence. The controller rejects a staged Agni checkout whose SHA differs from `AGNI_REV`, a missing lock entry, or a changing lock. It uses `nix build --no-update-lock-file` so missing locked dependencies cannot be resolved opportunistically.

The next conditional integration command (after the preflight passes and a disposable CoreOS VM1 is intended) is:

```sh
make fatline-vm-local PROVIDER=podman ARCH=arm64 SCOPE=nix-xd-arm \
  WORKLOAD_FLAKE=/workspaces/nix.xd20261111 WORKLOAD_REV="$WORKLOAD_REV" \
  AGNI_FLAKE=/workspaces/agni20261111/local/fatline AGNI_REV="$AGNI_REV" \
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
