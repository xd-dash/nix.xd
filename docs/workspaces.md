# Daily source workspaces

One checkout per repository and local calendar day: `<repository>YYYYMMDD`.
For example, `~/workspace/nix.xd20261111`. The date defaults to the host's local
timezone; WORKSPACE_VERSION explicitly selects a date for reproducibility.

```sh
make workspace WORKSPACE_BASE=codex/generic-runtime-state
cd "$(make -s workspace-path)"
```

Run workspace-path from the controller checkout before changing directory, or
use the absolute path printed by workspace. Make cannot change its parent shell's
working directory. A fresh checkout does not inherit the controller's untracked
nix-xd.local.mk; copy the generic example or set runtime variables explicitly.

The generic interface also supports other repositories:

```sh
make workspace WORKSPACE_REPO=xd-dash/grumble
make workspace WORKSPACE_REPO=dash-xd/agni
```

An omitted WORKSPACE_BASE uses the remote default branch for a new checkout.
A new checkout uses the existing remote `vYYYYMMDD` branch if present,
tracking `origin/vYYYYMMDD`. Otherwise it creates `vYYYYMMDD` from the
selected starting revision. This prevents an already-published dated branch
from being silently replaced with the repository default branch.
Same-day calls reuse that checkout without fetching, pulling or resetting it.
A checkout on another branch is rejected; this interface does not create feature
branches. WORKSPACE_BASE only selects the starting revision of a new checkout.

The next day's invocation creates a separate checkout from the selected remote
branch. Commit and push work needed by the next day before creating that checkout.
Old checkouts remain until explicitly removed. No symlink, `fresh` alias,
automatic prune, store deletion or credential copying is performed.

Targets:

- `workspace`: create/reuse today's checkout and print its path.
- `workspace-plan`: report the intended path and branch without creating them.
- `workspace-path`: print only the path, suitable for shell substitution.
- `workspace-check`: exercise checkout reuse, version-only branches, next-day separation
  and invalid/colliding destinations using a temporary local Git repository.
- `workspace-clean-plan`: list stale directories for the selected repository.
- `workspace-clean`: delete those directories, including uncommitted and untracked
  contents. Keep the selected dated checkout. Linked Git worktrees are removed
  through Git so their registration is also cleaned up.

Cleanup selects only direct children of WORKSPACE_ROOT named exactly like the
repository, `<repository>-fresh`, `<repository>-consolidated`, or
`<repository>YYYYMMDD` with a date older than WORKSPACE_VERSION. It leaves other
repositories, the retained version and future versions alone. Symlinks are not
followed. A retained dated checkout must already exist. Run cleanup from that
checkout, not from a directory being removed. No dirty-work preservation or
additional confirmation is required: workspace-clean explicitly requests deletion.
Before removal, cleanup restores owner read/write/search permission on directories
inside each selected stale checkout. This handles read-only Go module-cache
directories without changing file contents or following symlinks. The plan does
not change permissions. Cleanup verifies that each selected path was removed.

```sh
export NIX_XD_LOG_DIR="$HOME/.local/nix.xd/logs"
make workspace-clean-plan
make workspace-clean
```

Use the shared log override before cleanup; an old shell override pointing into
an obsolete checkout can otherwise recreate that directory on later commands.
Runtime containers and volumes have separate lifecycles and are not removed by
source-checkout cleanup.

WORKSPACE_ROOT defaults to `$HOME/workspace`. WORKSPACE_REPO accepts owner/repo,
HTTPS or SSH Git URLs. Ordinary Git authentication is reused. Branches outside the checkout's date are rejected by this interface. Direct Git commands remain under the developer's control.

Host source management belongs in Make. Building and running project flakes
continues through Nix-Alpine. Shared stores, runtime state and the overridden log
directory are independent of these dated source paths.

## Smoke ghxd source acquisition in Nix-Alpine (no host Git login)

`make workspace` and `make sync` remain developer-facing host Git operations. **Private, pinned qualification sources** should instead use `make ghxd`: the generic `nix.xd` flake owns the GHXD operator and builds the exact Smoke revision in the authoritative Nix-Alpine writer, while a separate rootless Podman container executes authentication and source retrieval with the Nix store mounted read-only. No GitHub token is passed to host Git or mounted in the Nix-Alpine writer.

After updating the current `nix.xd` checkout, stage it using the existing generic source copier:

```sh
make stage PROVIDER=podman MACHINE=coreos-arm64 ARCH=arm64 SCOPE=nix-xd-arm \
  WORKSPACES="$HOME/workspace" CHECKOUT=nix.xd20261111
make ghxd-volumes-provision PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
make ghxd PROVIDER=podman MACHINE=coreos-arm64 ARCH=arm64 SCOPE=nix-xd-arm \
  GHXD_ACTION=bootstrap
```

The selected flake defaults to the current `nix.xd` checkout directory (`GHXD_FLAKE=$(notdir $(CURDIR))` in Make), not an Agni application flake. Three persistent, owner-labeled Podman volumes are created idempotently by `ghxd-volumes-provision`:
- `nix-xd-state-secret-ghxd`: private age identity (0600), encrypted SOPS OAuth JSON, transient device request;
- `nix-xd-state-control-ghxd-home`: Smoke's ghxd environment/Go caches;
- `nix-xd-state-control-ghxd-workspaces`: exact detached Git worktrees and shared Git object databases.

The first authorization uses a **public** GitHub App/OAuth client ID that has device authorization enabled and enough granted access to read the selected repositories:

```sh
make ghxd MACHINE=coreos-arm64 SCOPE=nix-xd-arm GHXD_ACTION=auth-start \
  GHXD_CLIENT_ID=Iv1.YOUR_PUBLIC_CLIENT_ID
# Approve the printed URL and user code in the browser.
make ghxd MACHINE=coreos-arm64 SCOPE=nix-xd-arm GHXD_ACTION=auth-finish
```

The operator never logs access/refresh tokens. Device polling writes the OAuth response only in a private tmpfs and encrypts it to the dedicated secret volume before retaining it. `GHXD_ACTION=auth-refresh` explicitly rotates an existing encrypted refresh-token credential when needed. A missing/expired token fails source sync rather than falling back to host Git.

For the initial Probot integration, a **pinned bootstrap descriptor** in `examples/ghxd-agni-bootstrap.json` obtains Agni itself. The second source manifest is then read from that Agni checkout *inside Nix-Alpine*, rather than requiring a local macOS Agni checkout:

```sh
make ghxd MACHINE=coreos-arm64 SCOPE=nix-xd-arm GHXD_ACTION=source-sync \
  GHXD_SOURCE_MANIFEST="$PWD/examples/ghxd-agni-bootstrap.json"
make ghxd MACHINE=coreos-arm64 SCOPE=nix-xd-arm GHXD_ACTION=source-sync \
  GHXD_SOURCE_MANIFEST=/workspaces/agni-ghxd/local/fatline/qualification/probot-webhook-sources.json

make qualify PROVIDER=podman ARCH=arm64 MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  FLAKE=agni-ghxd/local/fatline TARGET='#qualify-integration' \
  ARGS='--scenario probot-webhook --phase preflight'
```

The manifest format is generic: `schema:1` plus `sources` mapping names to `repository` (`owner/repo`), `revision` (exact SHA), and `checkout` (safe workspace directory). The operator decrypts only during source synchronization, sets process-scoped `GH_TOKEN`, and uses Smoke's exact-SHA worktree seeder. Then a **second, credential-free Podman process** streams a source archive excluding Git administrative data into the authoritative owner's `/workspaces/<checkout>` and writes `.nix-xd-source-revision`. A different existing checkout never gets silently overwritten. No macOS Git authentication or manual source cloning is involved.

The GHXD execution path has not yet been live-qualified on this Podman machine. The initial integration preflight is source/client qualification only, not proof of a live webhook, durable Skymill settlement, or Logma/Logmash/SSE hint delivery.
