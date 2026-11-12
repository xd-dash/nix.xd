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

`make workspace` and `make sync` remain developer-facing host Git operations. For authenticated pinned qualification inputs use `make ghxd` instead; it does not invoke host `git clone`, `gh auth login`, or save a macOS Git credential.

The generic GHXD runner requires a staged application flake with `#ghxd-source-build` and `#ghxd-operator` (Agni's local Fatline flake supplies both). Source build happens **inside the authoritative Nix-Alpine owner** using a pinned Smoke revision and registers a Nix GC root. The separate one-shot Podman operator consumes the same Nix store **read-only**. No GitHub credential, age identity, or decrypted token is mounted into the writer.

One-time volumes (create-only, never delete/reinitialize existing volumes):

```sh
make ghxd-volumes-provision PROVIDER=podman MACHINE=coreos-arm64 SCOPE=nix-xd-arm
```

Three named labeled volumes are used:
- `nix-xd-state-secret-ghxd` (SOPS/age identity, encrypted token JSON and temporary device request);
- `nix-xd-state-control-ghxd-home` (Smoke ghxd Go environment and caches);
- `nix-xd-state-control-ghxd-workspaces` (exact detached Git worktrees and shared bare object databases).

Select the staged flake and public GitHub OAuth/GitHub App client ID, then authorize through a browser. GitHub must have enabled the device flow for that client:

```sh
make ghxd PROVIDER=podman ARCH=arm64 MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  FLAKE=agni20261111/local/fatline GHXD_ACTION=bootstrap

make ghxd PROVIDER=podman ARCH=arm64 MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  FLAKE=agni20261111/local/fatline GHXD_ACTION=auth-start GHXD_CLIENT_ID=Iv1.YOUR_PUBLIC_CLIENT_ID

# Visit the printed verification URL and enter the printed short user code.
make ghxd PROVIDER=podman ARCH=arm64 MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  FLAKE=agni20261111/local/fatline GHXD_ACTION=auth-finish
```

`auth-finish` polls the device authorization and encrypts the resulting OAuth JSON with SOPS/age before persisting it. Neither access nor refresh tokens are printed or passed through host Git. `GHXD_ACTION=auth-refresh` invokes Smoke's refresh operation using the encrypted refresh token; it is explicit, never triggered automatically while the source graph changes. Refresh token rotation is persisted before the next sync.

The pinned source manifest is an *application-owned*, non-secret JSON file (`schema:1`, `sources`: named maps of `repository`, `revision` and `checkout`). The generic runner must not infer a mutable branch for qualification. Example:

```sh
make ghxd PROVIDER=podman ARCH=arm64 MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  FLAKE=agni20261111/local/fatline GHXD_ACTION=source-sync \
  GHXD_SOURCE_MANIFEST="$HOME/workspace/agni20261111/local/fatline/qualification/probot-webhook-sources.json"
```

The operator decrypts only in a private tmpfs, exports `GH_TOKEN` to Smoke's exact-SHA seeding command, and verifies worktree identities. A second, credential-free process streams each checked-out source archive (excluding Git administrative data) into `/workspaces/<checkout>` within Nix-Alpine and records `.nix-xd-source-revision`. Existing destinations with different or unknown revisions fail closed; no host checkout is required. Agni then runs the existing application gate:

```sh
make qualify PROVIDER=podman ARCH=arm64 MACHINE=coreos-arm64 SCOPE=nix-xd-arm \
  FLAKE=agni20261111/local/fatline TARGET='#qualify-integration' \
  ARGS='--scenario probot-webhook --phase preflight'
```

The `ghxd` commands have not yet been qualified live in the ARM runtime. The bootstrap may need access to public Go dependencies; private source fetching requires a device token with sufficient repository access. The integration preflight does not prove a live GitHub webhook, Skymill settlement or SSE delivery.
