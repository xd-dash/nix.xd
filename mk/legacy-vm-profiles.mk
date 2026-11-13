## Historical, application-specific VM profile compatibility only.
# No new guests should be added to this Make include.
# Host-side accelerated CoreOS qualification is intentionally independent of the
# selected Nix execution provider. Artifacts must be exported before boot.
PROFILE ?= starwisp
COREOS_STATE_ROOT ?= $(HOME)/.local/state/nix-xd/coreos
COREOS_ARTIFACT_STATE ?=
COREOS_IMAGE ?=
COREOS_IMAGE_SHA256 ?=
COREOS_IGNITION ?=
COREOS_FIRMWARE ?=
COREOS_SSH_PORT ?= 2222
COREOS_RAM_MIB ?= 2048
COREOS_CPUS ?= 2
COREOS_GUEST_USER ?= wisp
COREOS_SSH_KEY ?=
COREOS_SSH_PUBLIC_KEY ?=
COREOS_ORPHANED_OVERLAY ?= 0
COREOS_READY_TIMEOUT_SEC ?= 900
COREOS_READY_RETRY_SEC ?= 10
COREOS_SSH_CONNECT_TIMEOUT_SEC ?= 10
COREOS_AGNI_REV ?=
COREOS_NIX_STORE_VOLUME ?=
COREOS_9P_GRANTS_FILE ?= $(GRANTS_FILE)
COREOS_IGNITION_OUTPUT ?=
COREOS_BUTANE_PROFILE ?=
COREOS_GUEST_PROBE_ROOTFS ?=
COREOS_PROBE_FLAKE ?= /workspaces/nix.xd
COREOS_GUEST_NIX_EXECUTABLE ?=
COREOS_GUEST_DYNAMIC_EXECUTABLE ?=
COREOS_GUEST_OCI_ARCHIVE ?=
COREOS_CONTAINER_NAME ?=
VMM ?= podman
COREOS_FLAKE ?= /workspaces/agni/qemu/coreos-live/local
COREOS_RUNNER_IMAGE ?= localhost/agni-coreos-qemu-runner:44.20261023.3.1-aarch64
# Export CoreOS configuration through Make's environment; never interpolate
# arbitrary path/key values into an executable shell assignment string.
export NIX_XD_MACHINE = $(MACHINE)
export NIX_XD_SCOPE = $(SCOPE)
export COREOS_FLAKE
export COREOS_RUNNER_IMAGE
export COREOS_VMM = $(VMM)
export COREOS_PROFILE = $(PROFILE)
export COREOS_STATE_ROOT
export COREOS_ARTIFACT_STATE
export COREOS_IMAGE
export COREOS_IMAGE_SHA256
export COREOS_IGNITION
export COREOS_FIRMWARE
export COREOS_SSH_PORT
export COREOS_RAM_MIB
export COREOS_CPUS
export COREOS_GUEST_USER
export COREOS_SSH_KEY
export COREOS_SSH_PUBLIC_KEY
export COREOS_ORPHANED_OVERLAY
export NIX_XD_FROM_MACHINE = $(FROM_MACHINE)
export COREOS_READY_TIMEOUT_SEC
export COREOS_READY_RETRY_SEC
export COREOS_SSH_CONNECT_TIMEOUT_SEC
export COREOS_AGNI_REV
export COREOS_NIX_STORE_VOLUME
export COREOS_9P_GRANTS_FILE
export COREOS_IGNITION_OUTPUT
export COREOS_BUTANE_PROFILE
export COREOS_GUEST_PROBE_ROOTFS
export COREOS_GUEST_OCI_ARCHIVE
export COREOS_GUEST_DYNAMIC_EXECUTABLE
export COREOS_GUEST_NIX_EXECUTABLE
export COREOS_CONTAINER_NAME

.PHONY: store-export-check coreos-container-build coreos-ignition-build coreos-preflight coreos-boot coreos-stop coreos-qualify coreos-reset-failed qualify-starwisp qualify-starwisp-shared
store-export-check:
	@NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_IMAGE='$(IMAGE)' COREOS_NIX_STORE_VOLUME='$(if $(COREOS_NIX_STORE_VOLUME),$(COREOS_NIX_STORE_VOLUME),$(SCOPE)-store)' bash bin/nix-xd-log "$(SCOPE)" store-export-check bash bin/nix-xd-store-export-check

coreos-container-build:
	@test "$(VMM)" = podman || { echo 'coreos-container-build requires VMM=podman' >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" coreos-container-build bash bin/nix-xd-coreos-podman build

coreos-ignition-build:
	@test "$(VMM)" = podman || { echo 'coreos-ignition-build requires VMM=podman' >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" coreos-ignition-build bash bin/nix-xd-coreos-podman ignition

coreos-reset-failed:
	@test "$(VMM)" = podman || { echo "coreos-reset-failed requires VMM=podman" >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" coreos-reset-failed bash bin/nix-xd-coreos-podman reset-failed

coreos-preflight coreos-boot coreos-stop:
	@case "$(VMM)" in \
	  podman) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-coreos-podman $(patsubst coreos-%,%,$@) ;; \
	  hvf) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-coreos-hvf $(patsubst coreos-%,%,$@) ;; \
	  *) echo 'VMM must be podman or hvf' >&2; exit 2 ;; \
	  esac

coreos-qualify:
	@bash bin/nix-xd-log "$(SCOPE)" coreos-qualify bash bin/nix-xd-wisp-ssh

# Prepare fresh closure outputs in the authoritative store, then run the
# existing guest 9P and nested Podman qualification. No Nix store copies.
qualify-starwisp-shared:
	@test "$(ARCH)" = arm64 && test "$(PROVIDER)" = podman && test "$(VMM)" = podman || { echo 'Shared-store Starwisp gate requires ARM64 Podman Machine' >&2; exit 2; }
	@COREOS_PROBE_FLAKE='$(COREOS_PROBE_FLAKE)' bash bin/nix-xd-log "$(SCOPE)" qualify-starwisp-shared bash bin/nix-xd-qualify-starwisp-shared

qualify-starwisp:
	@test "$(VMM)" = podman || { echo "qualify-starwisp requires VMM=podman" >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" qualify-starwisp bash bin/nix-xd-qualify-starwisp


.PHONY: workload-qualify
workload-qualify:
	@test "$(ARCH)" = arm64 && test "$(PROVIDER)" = podman && test "$(VMM)" = podman || { echo 'Current CoreOS VM adapter requires ARM64 Podman Machine' >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" workload-prepare bash bin/nix-xd-workload prepare
	@NIX_XD_QUALIFY_WORKLOAD=1 COREOS_NIX_STORE_VOLUME='$(SCOPE)-store' bash bin/nix-xd-log "$(SCOPE)" workload-qualify bash bin/nix-xd-qualify-starwisp

