# Nix-Alpine execution and dated source idioms

This document is normative for new nix.xd, Agni, Smoke and GHXD qualification
work. It extends [Daily source workspaces](workspaces.md), whose workspace
tool and tests already enforce the date-only branch convention.

## Ownership boundary

- **Host nix.xd** supplies the thin Make interface, architecture/provider
  selection, Nix-Alpine lifecycle, source staging, transport, grants and logs.
- **Nix-Alpine** owns the writable Nix store and exact, rooted Linux closures.
  Application-specific behavior is not implemented in its image/bootstrap.
- **Application flakes (Agni, etc.)** supply build, compose, qualification and
  activation actions. Execute those actions via nix.xd's generic `make run`
  or `make qualify`; do not duplicate them in platform-specific wrappers.
- **Smoke/GHXD** owns GitHub device authorization and exact-SHA source seeding.
  It runs with isolated secret volumes. The Nix-Alpine writer never receives
  the OAuth token.
- **CoreOS guest** reads the host-owned Nix store through the qualified
  read-only 9P mount. Application services use rootless user-systemd units.
  Generate runtime credentials outside Nix derivations and mount them only
  into the relevant processes.

## Source version and branch convention

- A new daily branch is **`vYYYYMMDD`**, for example `v20261112`.
  Dates are valid local-calendar dates. **Never name new source branches
  after a feature, ticket, component, qualification gate or actor.**
- A local workspace directory is **`<repository>YYYYMMDD`**,
  for example `nix.xd20261112` or `agni20261112`.
  For GHXD staged application sources, the same naming convention applies:
  `/workspaces/agni20261112`, `/workspaces/skymill20261112`.
- The date is the **workspace generation**, not a replacement for source
  identity. All source manifests and evidence MUST still record exact
  immutable 40-character commit SHAs. A branch or dated path alone is
  not a reproducible pin.
- Reuse the same-day branch/checkout. For new work on the next local day,
  create `v<newdate>` and `<repository><newdate>`, starting from the
  explicitly selected previous revision. Never force-move a published
  dated branch or overwrite an existing GHXD checkout with a different SHA.
- `WORKSPACE_BASE` is a *starting ref* when creating a new workspace,
  not the name of a new branch. Existing versioned remote branches take
  precedence, as verified by `make workspace-check`.
- Source directory names, Git branches, Nix store paths, and runtime state
  directories serve different roles: do not rename an active store root,
  persistent service scope, or credential volume merely because the date
  changes.

## Everyday workflow

From the existing nix.xd controller checkout:

```sh
make workspace-plan WORKSPACE_VERSION=20261112
make workspace WORKSPACE_VERSION=20261112
cd "$(make -s workspace-path WORKSPACE_VERSION=20261112)"
make workspace-check
```

Use `make ghxd GHXD_ACTION=source-sync GHXD_SOURCE_MANIFEST=...` for
the pinned component source set, then a dated Agni flake checkout:

```sh
make run FLAKE=agni20261112/local/fatline \
  TARGET='#qualify-integration' \
  ARGS='--scenario probot-webhook --phase service-profile'
```

Use a new manifest with a new date for a new candidate; do not quietly
rebind an existing checkout. Do not put credentials, GitHub tokens or
application configuration values into dated source names or derivations.

## Qualification

Run `make workspace-check` and `make check-static` for workspace
contracts. New VM1 GHXD candidate manifests must also pass
`make ghxd-source-version-check`, which verifies date-only checkout
names and exact source SHAs. This validation is additive; older GHXD
manifests remain readable to preserve prior qualification evidence.

Live guest activation is a separate, effectful phase. Source syncing,
Nix building, service-profile rendering and ACL candidate checks must
never implicitly restart Redis or update active user-systemd units.
