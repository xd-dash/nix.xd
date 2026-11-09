# Wisp Grml-derived ARM64 guest (experimental)

This is an initial **manifest/static qualification** flake, not a bootable image.
The parent `nix.xd` continues to own host orchestration. No Grml image build,
QEMU launch, or remote infrastructure mutation occurs in GitHub Actions.

Target: minimal headless systemd guest with rootless Podman, netavark,
aardvark-dns and pasta networking. Nginx will be a pinned OCI image,
not a guest package.

## Local static qualification

On an ARM64 Linux Nix builder (including a capable Nix-Alpine container):

```sh
nix flake check ./guests/grml
nix run ./guests/grml#qualify
```

## Remaining gates

1. Pin Grml/grml-live and Debian package snapshot, validate ARM64 class format.
2. Produce a rootfs and bootable ARM64 image; do not mistake a live ISO for a VM disk.
3. Qualify systemd boot, cgroup v2, rootless Podman, Quadlets and network DNS.
4. Qualify Nginx inbound port forwarding, reboot persistence and negative network tests.
5. Record boot-to-Wisp readiness, artifact digests, image provenance and cleanup.

Until those gates pass, this branch is NOT runtime-qualified.
