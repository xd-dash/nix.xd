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
A new checkout creates the version-only branch `vYYYYMMDD`.
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
