# Example opt-in builder profile for a rootless Podman ARM64 Nix-Alpine owner.
# Copy these settings into nix-xd.local.mk alongside the selected machine/scope.
# The authoritative /nix store remains STORE_VOLUME; these are separate writers.
BUILDER_CHROOT_STORES = grumble=$(SCOPE)-grumble-chroot experiments=$(SCOPE)-experiments-chroot

# Preserve seccomp filtering; permit only the extra syscalls demonstrated by
# the builder policy's generated OCI seccomp profile.
BUILDER_CHROOT_NAMESPACE = 1
BUILDER_CHROOT_SYSCALLS = 1

# Default is 'keep'. Only opt into 'disabled' when the controlled
# SELinux comparison in builder-chroot-profile.sh demonstrates necessity.
CHROOT_SELINUX = keep

# Plan without making changes:
# make builder-store-profile-plan
# On a new instance, after selecting the machine/scope:
# make bootstrap-builder-profile
# On an already bootstrapped and staged builder:
# make builder-store-profile-apply
