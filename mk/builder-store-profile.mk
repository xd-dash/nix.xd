# Opt-in builder profile for multiple writable chroot stores beside the authoritative /nix store.
# Chroot configuration is intentionally separate from read-only PEER_STORES.
BUILDER_CHROOT_STORES ?=
BUILDER_CHROOT_NAMESPACE ?= 1
BUILDER_CHROOT_SYSCALLS ?= 1

.PHONY: builder-store-profile-plan builder-store-profile-apply bootstrap-builder-profile
builder-store-profile-plan:
	@BUILDER_CHROOT_STORES='$(BUILDER_CHROOT_STORES)' \
	  BUILDER_CHROOT_NAMESPACE='$(BUILDER_CHROOT_NAMESPACE)' \
	  BUILDER_CHROOT_SYSCALLS='$(BUILDER_CHROOT_SYSCALLS)' \
	  bash bin/nix-xd-builder-store-profile plan

builder-store-profile-apply:
	@BUILDER_CHROOT_STORES='$(BUILDER_CHROOT_STORES)' \
	  BUILDER_CHROOT_NAMESPACE='$(BUILDER_CHROOT_NAMESPACE)' \
	  BUILDER_CHROOT_SYSCALLS='$(BUILDER_CHROOT_SYSCALLS)' \
	  NIX_XD_CHROOT_SELINUX='$(CHROOT_SELINUX)' \
	  bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-store-profile apply

# Explicit opt-in: existing builder bootstraps and Quadlets are unchanged.
# Stage the project flake before creating the syscall policy output.
bootstrap-builder-profile:
	@$(MAKE) --no-print-directory bootstrap
	@$(MAKE) --no-print-directory stage
	@$(MAKE) --no-print-directory builder-store-profile-apply
