# Encrypted runtime secrets

Only encrypted SOPS JSON/YAML documents belong here. The public age recipient is in [../.sops.yaml](../.sops.yaml).

The private age identity remains in a separate persistent Podman volume; it is never committed or placed in the Nix store. Decrypt at **runtime** using Smoke or Nix-provided SOPS/age, not during derivation evaluation or build. This folder initially contains no credentials. Existing local encrypted GHXD credentials are not moved by this configuration.

Never commit a plaintext secret, private identity, or Nix store output containing decrypted values. A tracked `.enc.json` or `.enc.yaml` filename alone does not establish encryption; check SOPS metadata before publishing.
