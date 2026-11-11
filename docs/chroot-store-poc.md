# Persistent chroot-store POC

This is generic Nix-Alpine infrastructure qualification, not Grumble application
implementation. Make selects and attaches a store; the actual build/qualification
controller runs from the runtime flake inside the existing Nix-Alpine container.

The Podman adapter adds a managed `<scope>.container.d/20-chroot-<name>.conf`
containing a writable named-volume mount at `/stores/<name>`. The base Quadlet,
image declaration and authoritative `/nix` volume are unchanged. A missing volume
is explicitly created by this provisioning operation. Nonempty unmarked volumes,
conflicting destinations, and volumes attached to another container are rejected.
Initialization uses a short-lived rootless Podman helper to set only the new
volume root's ownership. It never recursively changes existing store ownership.

The first attach restarts the Nix-Alpine owner once to apply the mount; do not run
it during other owner builds. CoreOS VM runners are separate and are not restarted.
A repeat attach validates/reuses the mount. The independent volume persists across
owner recreation while the managed declaration remains present. There is no
automatic volume deletion or migration.

Using the existing `fatline` Make function (only as a generic runtime selector):

```bash
fatline stage &&
fatline chroot-store-attach CHROOT_NAME=grumble &&
fatline chroot-store-qualify CHROOT_NAME=grumble
```

The default volume name is `<scope>-grumble-chroot`, deliberately distinct from
Grumble's separate builder-store volume. Override `CHROOT_VOLUME` explicitly if
needed. No Grumble checkout, application build, or new GitHub login is needed.
The configured shared logger records the attach and project-run operations.

## Gate

1. Confirm that the chroot path is a marked persistent mount and that the ordinary
   executor can create user/mount namespaces. Fail before builds if unavailable;
   do not disable seccomp, add owner privileges or change kernel policy silently.
2. Build a small fixture-tool closure, then copy only that declared closure into
   the chroot store. Both stores retain the logical directory `/nix/store`.
3. Instantiate independent outputs with unique names and build them concurrently.
   Record build timestamps and require their execution intervals to overlap.
4. Query both databases in both directions. Require each unique output to be
   valid only in its own store and require distinct physical database identities.
5. Execute the same fixture program in each store view. It invokes Nix explicitly
   against `local`, verifies the expected output/foreign denial, and reports the
   database identity visible at `/nix/var/nix/db/db.sqlite`.
6. Try deleting the rooted chroot fixture: require refusal and continued validity.
   Release only that fixture's root, delete that exact output, and verify the
   normal-store output remains valid. Never run authoritative-store GC or delete
   any authoritative-store output. The normal fixture's temporary root is then
   released; its output remains available for ordinary future lifecycle handling.

Evidence is written to `/stores/<name>/.poc/<id>.json`; failed runs keep their
records and roots for inspection. The final marker is
`CHROOT_STORE_POC_RESULT=passed`. Expected invalid-path/deletion-refusal messages
may appear during negative checks. Initial cache downloads can take longer than
the fixture's three-second builds; progress is streamed to the common log.

## Project store selection

`project-run PROJECT_STORE=local` uses the normal store. Selecting
`PROJECT_STORE=/stores/<name>` requires a marked persistent mount and passes
`--store` to the project invocation. The selected project's process runs in Nix's
chroot execution view. Its inherited `NIX_REMOTE=local` and an explicit inner
`--store local` refer to that view, not a second nested physical chroot path.
`NIX_XD_PROJECT_PHYSICAL_STORE` records the outer selection for diagnostics;
projects should not reuse that physical path as a nested `--store` argument.
An application can still explicitly select another declared store; this is a
runtime default, not a security isolation policy between same-user projects.

This POC does not qualify arbitrary mount paths, overlay stores, hostile workloads,
Grml ISO production, or the separate VM-local/guest-only store domains. It does
not modify Agni or Fatline application policy.
