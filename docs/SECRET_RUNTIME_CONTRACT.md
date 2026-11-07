# Runtime secrets and nested-flake execution contract

## Ownership

- **Nix-Alpine** owns Podman/systemd bootstrap, Nix build and flake execution, independent stores, store closure transfer, and host administration. It has no obligation to depend on Smoke.
- **Smoke** is an optional consumer/orchestrator: application qualification, GitHub OAuth and refresh, native Go SOPS/age, and scoped execution of nested flakes.
- **Flakes** declare immutable programs, dependencies, and public configuration. A child flake can run without Smoke; when it needs credentials it requests a runtime secret capability, not a secret as a Nix argument.
- **Local secrets repository** holds only encrypted SOPS documents, `.sops.yaml`, and public age recipients. Non-secret metadata may be copied to `/nix/store`. No plaintext credentials or private age identities are committed.

## Secret lifecycle

1. Bootstrap Nix-Alpine outside Nix derivations; mount the age identity from a private, persistent Podman volume. The writer has appropriate write access; read-only readers cannot rotate or replace it.
2. Evaluate/build flakes *without* access to the private identity. Encrypted SOPS documents and public recipients may be included as Nix inputs/store paths; they remain ciphertext.
3. At runtime, Smoke's native SOPS implementation, or the flake-provided `sops`/`age` CLI, decrypts from the mounted private identity. Provide secrets in process memory or a mode-0600 file under a process-private runtime directory (prefer tmpfs), and remove the file after use.
4. Keep decrypted values out of Nix derivation attributes, `builtins.readFile`, `builtins.toFile`, `writeText`, `runCommand`, `passAsFile`, flake arguments, `NIX_CONFIG`, Nix command-line arguments, process logs, build sandboxes, and any path subsequently copied to the Nix store. Do not run secret-dependent work in Nix build phases.
5. Refreshed credentials are a synchronized writer-owned transaction: encrypt and atomically replace the *ciphertext* in the writable secrets location; readers only consume complete snapshots. Refresh is never concurrent, nested, or retried blindly.

The existing local `/workspaces/.private/sops/ghxd.enc.json` is an **ignored runtime ciphertext path**, not source-controlled plaintext. Before moving it into any tracked encrypted-secrets repository, explicitly qualify the new layout and ensure the private identity and decrypted material remain outside Git and `/nix/store`.

## Nested, serial, and recursive composition

- A parent flake/application may invoke other flakes via Nix-Alpine's supported run/check/build/qualify interface; Smoke is optional at each level.
- Smoke may invoke a nested Nix-Alpine qualification runner. It must pass an immutable flake reference, bounded depth, explicit scope, serialized credential-writer ownership, and a structured result. Child operations inherit only deliberately delegated runtime capabilities, not all parent environment variables or age keys.
- Administrative operations (Podman, systemd, volume management, filesystem setup) belong to the **host-side Nix-Alpine control interface**, not an unprivileged build derivation. A guest may request a *narrow allowlisted* host operation through an explicitly authenticated control channel; do not mount the host Podman socket merely to call Make recursively.
- In-guest use of Nix-Alpine's Makefile for build/qualification is permitted where the command actually runs in that execution context. Host-only targets require host dispatch; `make` itself does not confer host authority.
- Independently qualified Nix stores transfer **only closure content** with Nix copy/export/import. They must not carry private identities or plaintext credentials. Shared secrets access is a separate runtime mount contract, never evidence of store sharing.

## Required qualification

For the ARM writer and independent reader: prove separate flake invocations can consume the existing encrypted credential in memory; both can perform an authenticated GitHub API operation; writer can serialize a single refresh and atomically publish the replacement; both can consume the replacement; independent-store closure export/import works; all secret values and age private keys remain absent from store paths, logged output, and tracked Git files.

**Existing evidence:** native SOPS encryption, cross-container decryption, local device authorization, and ciphertext persistence after bootstrap refresh passed. Live cross-flake token consumption, OAuth refresh, and independent-store closure import are implemented as a new local qualification but remain unqualified on the target Mac until executed.

Run the new qualification against the already bootstrapped writer/reader:

```sh
make qualify-ghxd-runtime PROVIDER=podman MACHINE=podman-machine-default SCOPE=nix-xd-smoke-podman ROTATE=0
```

`ROTATE=0` performs live authenticated API requests from both flakes and both containers after copying immutable Nix closures to the reader's independent Nix store. It never modifies the credential.

`ROTATE=1` additionally performs **one live GitHub refresh-token exchange**, which immediately invalidates the prior access/refresh pair, then atomically replaces SOPS ciphertext on the writer and tests the new pair in both containers. It requires a readable refresh token and verified source/flake prerequisites. It intentionally skips pre-refresh live API checks because access tokens expire after eight hours, but post-refresh probes must succeed against both containers and flake wrappers. The reader's private identity mount stays read-only. The exchange and on-disk replacement cannot be made one atomic transaction with GitHub, so interruption after GitHub rotates but before local durable publication requires explicit recovery (device authorization), not blind retry. Never run multiple refresh qualifiers concurrently.

```sh
make qualify-ghxd-runtime PROVIDER=podman MACHINE=podman-machine-default SCOPE=nix-xd-smoke-podman ROTATE=1
```

The plain flake uses a fresh Nix-launched wrapper. The nested flake dispatches that plain flake with bounded recursion. The reader executes imported closures directly rather than re-evaluating nixpkgs in a separate store; both invoke the same workspace-mounted Smoke executable and SOPS credential. This proves flake *runtime closure* transfer, not a Nix-built Smoke artifact or a generic host-admin RPC.
