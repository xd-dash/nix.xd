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
make workspace WORKSPACE_REPO=dash-xd/agni WORKSPACE_TOPIC=startup
```

An omitted WORKSPACE_BASE uses the remote default branch for a new checkout.
A new checkout creates `work/YYYYMMDD/<topic>`; the default topic is `work`.
Same-day calls reuse that checkout without fetching, pulling or resetting it.
Selecting another WORKSPACE_TOPIC switches or creates a same-day branch only
when the working tree is clean. New topics branch from the current local HEAD.
WORKSPACE_BASE only selects the starting revision of a newly created checkout.

The next day's invocation creates a separate checkout from the selected remote
branch. Commit and push work needed by the next day before creating that checkout.
Old checkouts remain until explicitly removed. No symlink, `fresh` alias,
automatic prune, store deletion or credential copying is performed.

Targets:

- `workspace`: create/reuse today's checkout and print its path.
- `workspace-plan`: report the intended path and branch without creating them.
- `workspace-path`: print only the path, suitable for shell substitution.
- `workspace-check`: exercise checkout reuse, dated branches, next-day separation
  and invalid/colliding destinations using a temporary local Git repository.

WORKSPACE_ROOT defaults to `$HOME/workspace`. WORKSPACE_REPO accepts owner/repo,
HTTPS or SSH Git URLs. Ordinary Git authentication is reused. WORKSPACE_TOPIC is
a short branch suffix; branches outside the checkout's date are rejected by this
interface. Direct Git commands remain under the developer's control.

Host source management belongs in Make. Building and running project flakes
continues through Nix-Alpine. Shared stores, runtime state and the overridden log
directory are independent of these dated source paths.
