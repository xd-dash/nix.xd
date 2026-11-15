# nix.xd — contributor/agent contract

Read [docs/architecture-v20261115.md](docs/architecture-v20261115.md) before changing bootstrappers, volume grants, Make targets or guest transport.

- Generic lifecycle, staged immutable checkouts, Nix/store grants, source-locked flake execution and SSH transport only. Do not add application-specific Shoal/Fatline/Probot policy.
- Mac bootstrap is disposable; only bootstrap/explicit host resource boundary may mutate macOS. The old project-host-run and host Git stage are documented transitional exceptions, **not** approved new idioms.
- Use rootless Podman, dedicated volumes, read-only store readers, isolated secrets, `~/.local/state/nix-xd`, `~/.local/nix.xd/logs`.
- New application stages belong in Agni or Smoke. Source revisions must be full SHAs, never moving branch names at execution.
- Before edits run `make architecture-check`; for cross-repo ownership run `make architecture-audit AGNI_DIR=... SMOKE_DIR=...`; follow with `make check-static` as applicable.
- Do not declare the Mac-only GHXD host adapter retired until a Nix-Alpine-only live source/credential/store qualification exists.
