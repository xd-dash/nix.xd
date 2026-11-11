# Opt-in builder profile for multiple writable chroot stores beside the authoritative /nix store.
# Chroot configuration is intentionally separate from read-only PEER_STORES.
BUILDER_CHROOT_STORES ?=
BUILDER_CHROOT_NAMESPACE ?= 1
BUILDER_CHROOT_SYSCALLS ?= 1
INITIAL_PROFILE ?= 0
INITIAL_CHROOT_STORES ?=

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

# Staging uses the container's writable layer. A Quadlet restart recreates it,
# so first settle volume/namespace changes, stage for seccomp build, then restage
# after any policy restart. Never assume /workspaces survives a unit restart.
.PHONY: builder-store-profile-complete
builder-store-profile-complete:
	@$(MAKE) --no-print-directory builder-store-profile-apply BUILDER_CHROOT_SYSCALLS=0
	@$(MAKE) --no-print-directory stage
	@$(MAKE) --no-print-directory builder-store-profile-apply
	@$(MAKE) --no-print-directory stage

# Explicit opt-in: existing builder bootstraps and Quadlets are unchanged.
bootstrap-builder-profile:
	@$(MAKE) --no-print-directory builder-store-profile-plan
	@test "$(PROVIDER)" = podman || { echo 'Builder chroot bootstrap currently requires PROVIDER=podman' >&2; exit 2; }
	@if [[ '$(INITIAL_PROFILE)' == 1 ]]; then \
	  test -n '$(INITIAL_CHROOT_STORES)' || { echo 'Missing INITIAL_CHROOT_STORES' >&2; exit 2; }; \
	  $(MAKE) --no-print-directory bootstrap; \
	  $(MAKE) --no-print-directory stage; \
	else \
	  $(MAKE) --no-print-directory bootstrap; \
	  $(MAKE) --no-print-directory builder-store-profile-complete; \
	fi

# Run only on a disposable, freshly bootstrapped builder scope.
# The first application may restart the builder; the second must not.
.PHONY: builder-store-profile-qualify-idempotence
builder-store-profile-qualify-idempotence:
	@test "$(PROVIDER)" = podman || { echo 'Idempotence gate requires Podman' >&2; exit 2; }
	@$(MAKE) --no-print-directory builder-store-profile-apply
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' \
	  BUILDER_CHROOT_STORES='$(BUILDER_CHROOT_STORES)' \
	  BUILDER_CHROOT_NAMESPACE='$(BUILDER_CHROOT_NAMESPACE)' \
	  BUILDER_CHROOT_SYSCALLS='$(BUILDER_CHROOT_SYSCALLS)' \
	  NIX_XD_CHROOT_SELINUX='$(CHROOT_SELINUX)' \
	  bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-store-idempotence

# Store-only static gate: independent of Fatline VM and application tests.
.PHONY: builder-store-profile-check
builder-store-profile-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory builder-store-profile-check-internal

.PHONY: builder-store-profile-check-internal
builder-store-profile-check-internal:
	@bash -n bin/nix-xd-builder-store-profile bin/nix-xd-builder-store-idempotence \
	  bin/nix-xd-builder-store-qualify-fresh bin/nix-xd-builder-store-maintenance \
	  bin/nix-xd-chroot-attach bin/nix-xd-builder-profile \
	  runtime/chroot-attach.sh runtime/builder-chroot-profile.sh runtime/builder-chroot-syscalls.sh
	@python3 tests/builder-stores.py
	@python3 tests/builder-store-profile.py
	@python3 tests/builder-store-fresh.py
	@python3 tests/chroot-attach.py
	@echo 'BUILDER_STORE_PROFILE_STATIC_RESULT=passed'

# One logged, fail-closed fresh ARM builder qualification.
# Refuses any existing qualification image, container, Quadlet or volume.
QUALIFY_STORE_SCOPE ?= nix-xd-arm-chroot-qualify
QUALIFY_STORE_IMAGE ?= localhost/nix-xd:arm64-chroot-qualify
.PHONY: builder-store-profile-qualify-fresh
builder-store-profile-qualify-fresh:
	@test "$(PROVIDER)" = podman && test "$(ARCH)" = arm64 || { echo 'Fresh store profile qualification requires ARM64 Podman' >&2; exit 2; }
	@NIX_XD_QUALIFY_SCOPE='$(QUALIFY_STORE_SCOPE)' \
	  NIX_XD_QUALIFY_IMAGE='$(QUALIFY_STORE_IMAGE)' \
	  NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SYSTEM='$(NIX_SYSTEM)' \
	  NIX_XD_MACHINE='$(MACHINE)' NIX_XD_PEER_STORES='$(PEER_STORES)' \
	  BUILDER_CHROOT_NAMESPACE='$(BUILDER_CHROOT_NAMESPACE)' \
	  BUILDER_CHROOT_SYSCALLS='$(BUILDER_CHROOT_SYSCALLS)' \
	  NIX_XD_CHROOT_SELINUX='$(CHROOT_SELINUX)' \
	  bash bin/nix-xd-log "$(QUALIFY_STORE_SCOPE)" builder-store-profile-qualify-fresh \
	    bash bin/nix-xd-builder-store-qualify-fresh

# Resume an incomplete qualification only if the exact scoped resources exist.
# Do not create a new builder or erase any existing Nix store.
.PHONY: builder-store-profile-qualify-resume
builder-store-profile-qualify-resume:
	@test "$(PROVIDER)" = podman && test "$(ARCH)" = arm64 || { echo 'Resume requires ARM64 Podman' >&2; exit 2; }
	@NIX_XD_QUALIFY_SCOPE='$(QUALIFY_STORE_SCOPE)' \
	  NIX_XD_QUALIFY_IMAGE='$(QUALIFY_STORE_IMAGE)' \
	  NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SYSTEM='$(NIX_SYSTEM)' \
	  NIX_XD_MACHINE='$(MACHINE)' NIX_XD_PEER_STORES='$(PEER_STORES)' \
	  BUILDER_CHROOT_NAMESPACE='$(BUILDER_CHROOT_NAMESPACE)' \
	  BUILDER_CHROOT_SYSCALLS='$(BUILDER_CHROOT_SYSCALLS)' \
	  NIX_XD_CHROOT_SELINUX='$(CHROOT_SELINUX)' \
	  bash bin/nix-xd-log "$(QUALIFY_STORE_SCOPE)" "$@" \
	    bash bin/nix-xd-builder-store-qualify-fresh resume

# Inventory is read-only. Cleanup is limited to the explicit *-qualify scope.
.PHONY: builder-runtime-inventory builder-store-profile-qualify-clean
builder-runtime-inventory:
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' \
	  NIX_XD_QUALIFY_SCOPE='$(QUALIFY_STORE_SCOPE)' \
	  NIX_XD_QUALIFY_IMAGE='$(QUALIFY_STORE_IMAGE)' \
	  bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-store-maintenance inventory

QUALIFY_RESET_CONFIRM ?=
builder-store-profile-qualify-clean:
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' \
	  NIX_XD_QUALIFY_SCOPE='$(QUALIFY_STORE_SCOPE)' \
	  NIX_XD_QUALIFY_IMAGE='$(QUALIFY_STORE_IMAGE)' \
	  NIX_XD_QUALIFY_RESET_CONFIRM='$(QUALIFY_RESET_CONFIRM)' \
	  bash bin/nix-xd-log "$(QUALIFY_STORE_SCOPE)" "$@" bash bin/nix-xd-builder-store-maintenance clean-qualify

# Explicit cleanup of dangling Podman images only; does not touch volumes.
DANGLING_PRUNE_CONFIRM ?=
.PHONY: builder-image-prune-dangling
builder-image-prune-dangling:
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' \
	  NIX_XD_QUALIFY_SCOPE='$(QUALIFY_STORE_SCOPE)' \
	  NIX_XD_QUALIFY_IMAGE='$(QUALIFY_STORE_IMAGE)' \
	  NIX_XD_DANGLING_PRUNE_CONFIRM='$(DANGLING_PRUNE_CONFIRM)' \
	  bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-store-maintenance prune-dangling
