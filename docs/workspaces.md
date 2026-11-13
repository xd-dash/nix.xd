# CalVer source worktrees

Use ZeroVer CalVer candidate branches of form cal/0.YYYYMMDD.N.
Matching worktrees are ~/workspace/<repository>YYYYMMDD.N.
Qualification evidence pins exact commits, flake inputs, VM binding and artifact digests.
Tags v0.YYYYMMDD.N are reserved for qualified release identities.

The host canonical bare store is ~/workspace/.repos/<repository>.git.
Worktrees share Git objects and refs but have separate indexes and branches.
Existing full clones and older dated workspaces are preserved.

From an existing nix.xd Make controller:

    make workspace-init WORKSPACE_REPO=xd-dash/nix.xd
    make workspace WORKSPACE_REPO=xd-dash/nix.xd WORKSPACE_VERSION=20261113.0 WORKSPACE_BASE=cal/0.20261113.0
    make workspace-list WORKSPACE_REPO=xd-dash/nix.xd

Workspace opens an exact candidate. A remote branch of the same name wins,
otherwise WORKSPACE_BASE supplies the starting commit. Refresh always
allocates the next unused sequence for the selected calendar day:

    make workspace-refresh WORKSPACE_VERSION=20261113.0 WORKSPACE_BASE=cal/0.20261113.0

Refresh never deletes an earlier branch, checkout or state directory.
The current checkout is not silently advanced. A same-day .N sequence is
allocated per repository, not globally across the organization.

PR creation (requires authenticated GitHub CLI):

    make workspace-pr WORKSPACE_VERSION=20261113.0 WORKSPACE_PR_BASE=v20261112

It pushes the selected branch and opens or reuses its draft PR.
Remote CI can qualify it. A PR is not itself qualification evidence.
To remove a worktree AFTER its PR merged, explicitly run:

    make workspace-remove-plan WORKSPACE_VERSION=20261113.0
    make workspace-remove WORKSPACE_VERSION=20261113.0 WORKSPACE_REMOVE_CONFIRM=cal/0.20261113.0

Removal retains the Git branch and canonical store; closed-unmerged PRs
are not eligible. The old workspace-clean targets now fail closed.

Make sync uses the canonical store for newly created immutable source
checkouts; the source is detached at the selected branch head and must
match REV when supplied. An existing independent checkout is never
silently reset or migrated. Make stage accepts linked worktrees and
archives only committed source into Nix-Alpine.

Development worktrees are distinct from Smoke's future pinned,
multi-repository qualification workspace. Android repo manifests record
qualified source SHAs and do not substitute for flake.lock or go.mod.

Source remains in ~/workspace; persistent state belongs outside Git in
~/.local/state/nix-xd, and host logs retain the configured
~/.local/nix.xd/logs path. VM overlays, Podman volumes and GC roots have
separate installation ownership; their uninstall contracts are not
implemented by worktree deletion.

This source lifecycle neither modifies the running CoreOS Starwisp VM
nor establishes Shoal networking, Fatline services or Grml equivalence.
