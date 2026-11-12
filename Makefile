# Generic Nix-Alpine orchestration; applications supply their own flakes and gates.
SHELL := /bin/bash
.DEFAULT_GOAL := help

NIX_XD_CONFIG ?= $(CURDIR)/nix-xd.local.mk
-include $(NIX_XD_CONFIG)

PROVIDER ?= podman
# Architecture is selected at orchestration time, independent of provider.
# Native x86_64 runtime bootstrap is a separate adapter and is not yet qualified.
HOST_ARCH := $(shell uname -m)
ARCH ?= $(if $(filter arm64 aarch64,$(HOST_ARCH)),arm64,$(if $(filter x86_64 amd64,$(HOST_ARCH)),amd64,unsupported))
ifeq ($(ARCH),arm64)
NIX_SYSTEM := aarch64-linux
else ifeq ($(ARCH),amd64)
NIX_SYSTEM := x86_64-linux
else
$(error Unsupported ARCH=$(ARCH); expected arm64 or amd64)
endif
MODULES ?=
QUALIFY_APP ?= $(if $(strip $(MODULES)),0,1)
MACHINE ?= $(shell cat .state/active-podman-machine 2>/dev/null || echo podman-machine-default)
FROM_MACHINE ?= podman-machine-default
TRANSFER_IMAGE ?= localhost/agni-coreos-qemu-runner:44.20261023.3.1-aarch64
MACHINE_PROVIDER ?= applehv
MACHINE_CPUS ?= 6
MACHINE_MEMORY_MIB ?= 8192
MACHINE_DISK_GIB ?= 120
MACHINE_DEFAULT ?= 0
MACHINE_BOOTSTRAP ?= 1
LEGACY_PURGE_CONFIRM ?=
ARM_RESET_CONFIRM ?=
MACHINE_VERIFY ?= 0
MACHINE_ENV = NIX_XD_MACHINE="$(MACHINE)" NIX_XD_MACHINE_PROVIDER="$(MACHINE_PROVIDER)" NIX_XD_MACHINE_CPUS="$(MACHINE_CPUS)" NIX_XD_MACHINE_MEMORY_MIB="$(MACHINE_MEMORY_MIB)" NIX_XD_MACHINE_DISK_GIB="$(MACHINE_DISK_GIB)" NIX_XD_MACHINE_DEFAULT="$(MACHINE_DEFAULT)" NIX_XD_MACHINE_BOOTSTRAP="$(MACHINE_BOOTSTRAP)" NIX_XD_MACHINE_VERIFY="$(MACHINE_VERIFY)"
SCOPE ?= $(if $(filter arm64,$(ARCH)),nix-xd-arm,nix-xd-amd64)
IMAGE ?= localhost/nix-xd:$(ARCH)
WORKSPACES ?= $(abspath $(CURDIR)/..)
DATA_MOUNTS ?=
GRANTS_FILE ?=
export NIX_XD_DATA_MOUNTS = $(DATA_MOUNTS)
export NIX_XD_GRANTS_FILE = $(GRANTS_FILE)
REPO ?=
BRANCH ?= main
REV ?=
SYNC_NAME ?= $(notdir $(REPO))
CHECKOUT ?= $(SYNC_NAME)
FLAKE ?= .
TARGET ?=
ARGS ?=
CMD ?= nix --version
HASH := \#
PLAN_TARGET ?=
OS := $(shell uname -s)

TASK_ENV = NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SYSTEM='$(NIX_SYSTEM)' NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_WORKSPACES='$(WORKSPACES)' NIX_XD_CHECKOUT='$(CHECKOUT)' NIX_XD_FLAKE='$(FLAKE)' NIX_XD_TARGET='$(TARGET)' NIX_XD_ARGS='$(ARGS)' NIX_XD_CMD='$(CMD)' 
TASK = $(TASK_ENV) bash bin/nix-xd-task

GHXD_FLAKE ?= $(notdir $(CURDIR))
GHXD_ACTION ?= bootstrap
GHXD_CLIENT_ID ?=
GHXD_SOURCE_MANIFEST ?=
GHXD_BUILD_APP ?= $(HASH)ghxd-source-build
GHXD_PACKAGE ?= $(HASH)ghxd-operator
GHXD_PROGRAM ?= nix-xd-ghxd-operator
.PHONY: ghxd ghxd-volumes-provision
ghxd-volumes-provision:
	@$(MAKE) state-volume-provision MACHINE='$(MACHINE)' STATE_KIND=secret STATE_NAME=ghxd
	@$(MAKE) state-volume-provision MACHINE='$(MACHINE)' STATE_KIND=control STATE_NAME=ghxd-home
	@$(MAKE) state-volume-provision MACHINE='$(MACHINE)' STATE_KIND=control STATE_NAME=ghxd-workspaces

ghxd:
	@test "$(PROVIDER)" = podman || { echo 'GHXD currently requires Podman provider' >&2; exit 2; }
	@test -n "$(GHXD_FLAKE)" || { echo 'Select staged GHXD controller flake' >&2; exit 2; }
	@$(TASK_ENV) NIX_XD_FLAKE='$(GHXD_FLAKE)' NIX_XD_IMAGE='$(IMAGE)' NIX_XD_GHXD_CLIENT_ID='$(GHXD_CLIENT_ID)' NIX_XD_GHXD_MANIFEST='$(GHXD_SOURCE_MANIFEST)' NIX_XD_GHXD_BUILD_APP='$(GHXD_BUILD_APP)' NIX_XD_GHXD_PACKAGE='$(GHXD_PACKAGE)' NIX_XD_GHXD_PROGRAM='$(GHXD_PROGRAM)' bash bin/nix-xd-log "$(SCOPE)" "ghxd-$(GHXD_ACTION)" bash bin/nix-xd-ghxd '$(GHXD_ACTION)'

.PHONY: ghxd-auth-inventory
.PHONY: help self-update bootstrap plan image-build machine-init machine-check machine-handoff machine-select machine-start machine-stop start stop restart status logs shell exec ps inspect store-info store-diagnose store-roots-inspect store-roots-apply sync clone stage show check build path-info run develop compose qualify qualify-process qualify-service qualify-composition qualify-plan check-static

help:
	@printf '%s\n' \
	  'make tenant-storage-qualify  Disposable UID/GID, SELinux, sharing and scoped deletion gate on the selected Podman host' \
	  'make bootstrap-profile-local BUILDER_CHROOT_STORES="name=volume ..."  First-start profile, readiness and isolated-store qualification' \
	  'make bootstrap ARCH=arm64|amd64 PROVIDER=podman  Bootstrap selected host architecture' \
	  'make bootstrap ARCH=amd64 PROVIDER=podman  Direct-volume native Linux x86_64 runtime' \
	  'make qualify MODULES=store-recreation ARCH=arm64|amd64  Shared store recreation gate' \
	  'make machine-init MACHINE=... MACHINE_MEMORY_MIB=8192 MACHINE_CPUS=6 MACHINE_DISK_GIB=120' \
	  'make machine-check MACHINE=... (enforce minimum requested VM resources)' \
	  'make store-export-check MACHINE=...    Verify rootless read-only Nix volume sharing' \
	  'make arm-rebootstrap-diagnose|arm-rebootstrap-plan|arm-rebootstrap-reset|arm-rebootstrap-bootstrap|arm-rebootstrap-verify' \
	  'make arm-qualify-recreation MACHINE=... SCOPE=...    Legacy alias for shared store recreation gate' \
	  'make arm-wind-down-plan|arm-wind-down-stop       Log provider inventory and stop known nix.xd workloads' \
	  'make arm-inspect-legacy                         Inspect old Podman Machine then stop it' \
	  'make arm-purge-legacy-plan|arm-purge-legacy      Remove duplicate Apple stores and old Podman VM' \
	  'make arm-rebootstrap MACHINE=... SCOPE=... ARM_RESET_CONFIRM=ERASE:<machine>:<scope>:<scope>-store' \
	  'make machine-handoff FROM_MACHINE=... MACHINE=... (transfer CoreOS image, preserve Nix store)' \
	  'make image-build                            Build Nix-Alpine OCI image' \
	  'make sync REPO=owner/repo BRANCH=... [REV=sha] [SYNC_NAME=path]' \
	  'make stage CHECKOUT=path                     Stage committed checkout at /workspaces/path' \\
	  'make ghxd-auth-inventory MACHINE=... SCOPE=...  Inspect GHXD ciphertext and age volume presence (no secrets)' \
	  'make ghxd-volumes-provision MACHINE=...  Provision isolated GHXD credentials, tool-home, sources' \
	  'make ghxd FLAKE=path GHXD_ACTION=bootstrap|auth-start|auth-finish|source-sync' \
	  'make show|check|build|path-info FLAKE=path TARGET=$(HASH)output' \
	  'make run FLAKE=path TARGET=\x23app ARGS="..."' \
	  'make compose|qualify|qualify-process|qualify-service|qualify-composition' \
	  'make qualify MODULES=secrets ARCH=arm64  Optional age/SOPS runtime qualification' \
	  'make qualify QUALIFY_APP=1 MODULES=secrets FLAKE=path  Flake qualification plus modules' \
	  'make qualify-plan FLAKE=path PLAN_TARGET=\x23app (application-owned plan)' \
	  'make start|stop|restart|status|logs|shell|exec|ps|inspect|store-info' \
	  'make store-diagnose MACHINE=... SCOPE=...  Log read-only Nix store inventory' \
	  'make builder-store-profile-plan|builder-store-profile-check  Validate alternate store profile without touching the VM' \
	  'make bootstrap-builder-profile  Bootstrap an opt-in multi-chroot Nix-Alpine owner' \
	  'make builder-store-profile-qualify-resume  Resume an incomplete isolated builder qualification' \
	  'make builder-store-profile-qualify-atomic MACHINE=...  Fresh complete first-start Quadlet qualification' \
	  'make builder-store-profile-qualify-atomic-resume MACHINE=...  Retry partial prestart without deleting stores' \
	  'make builder-store-profile-atomic-clean QUALIFY_RESET_CONFIRM=ERASE:nix-xd-arm-atomic-qualify  Scope-only cleanup' \
	  'make builder-store-profile-qualify-fresh  One-shot isolated fresh bootstrap + idempotence' \
	  'make builder-runtime-inventory|builder-store-profile-qualify-clean  Inventory and scoped cleanup' \
	  'make workspace-inventory  Read-only Git worktree and stale workspace metadata inspection' \
	  'make nix-store-check|maintenance-review  Combined store contracts and read-only cleanup review' \
	  'make state-volume-plan|state-volume-provision|state-volume-inspect STATE_KIND=control|vm|application|secret STATE_NAME=... MACHINE=...' \
	  'make state-volume-export STATE_KIND=... STATE_NAME=... STATE_EXPORT_PATH=/absolute/path.tar MACHINE=...' \
	  'make grants-plan|grants-execute GRANTS_FILE=... FLAKE=... TARGET=... PROGRAM=...' \
	  'make grants-credentials-import GRANTS_FILE=... CREDENTIAL_IDENTITY=... CREDENTIAL_KNOWN_HOSTS=...' \
	  'make grants-transport-qualify GRANTS_FILE=... FLAKE=... BUILD_APP=... RUN_PACKAGE=... PROGRAM=...' \
	  'make builder-image-prune-dangling DANGLING_PRUNE_CONFIRM=YES  Remove dangling images only' \
	  'make store-isolation-static|store-isolation-check  Independent Nix-Alpine writer checks' \
	  'make workload-prepare|workload-inspect|workload-activate|workload-stop WORKLOAD=starwisp-probe' \
	  'make store-roots-inspect|store-roots-apply MACHINE=... SCOPE=...  Inspect or pin Starwisp closures' \
	  'make qualify-starwisp COREOS_SSH_KEY=...      Full ARM64 Starwisp boot/Wisp/shutdown gate' \
\t  'make qualify-starwisp-shared COREOS_SSH_KEY=...  Build current store closures and qualify guest 9P' \\\n\t  'make guest-app FLAKE=path TARGET=\\x23package GUEST_APP_REV=sha ARGS_JSON=...  Run store-backed guest script' \\
	  'make self-update                             Fast-forward this nix.xd checkout' \
	  'make check-static                            Host-independent static checks'

ghxd-auth-inventory:
	@test "$(PROVIDER)" = podman || { echo 'GHXD inventory requires Podman' >&2; exit 2; }
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-ghxd-inventory

self-update:
	@test -z "$(git status --porcelain --untracked-files=no)" || { echo "Tracked edits detected; commit or stash before self-update" >&2; exit 1; }
	@bash bin/nix-xd-log "$(SCOPE)" self-update git pull --ff-only

# Common user interface; architecture-specific bootstrap adapters are modular.
include mk/bootstrap-arm64.mk
include mk/bootstrap-amd64.mk

bootstrap: bootstrap-$(ARCH)


# Explicitly gated ARM64 Podman Machine volume rebuild. A single outer logger
# captures teardown, new direct-volume bootstrap and read-only export evidence.
ARM_REBOOTSTRAP_ENV = NIX_XD_MACHINE="$(MACHINE)" NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" NIX_XD_CONFIRM_RESET="$(ARM_RESET_CONFIRM)"
.PHONY: arm-qualify-recreation arm-rebootstrap-diagnose arm-rebootstrap-plan arm-rebootstrap-reset arm-rebootstrap-bootstrap arm-rebootstrap-verify arm-rebootstrap
arm-qualify-recreation:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-qualify-recreation bash arm/qualify-recreation-podman.sh
arm-rebootstrap-diagnose:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap-diagnose bash arm/rebootstrap-podman.sh diagnose
arm-rebootstrap-plan:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap-plan bash arm/rebootstrap-podman.sh preflight
arm-rebootstrap-reset:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap-reset bash arm/rebootstrap-podman.sh reset
arm-rebootstrap-bootstrap:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap-bootstrap bash arm/rebootstrap-podman.sh bootstrap
arm-rebootstrap-verify:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap-verify bash arm/rebootstrap-podman.sh verify
arm-rebootstrap:
	@test "$(PROVIDER)" = podman || { echo "Requires PROVIDER=podman" >&2; exit 2; }
	@$(ARM_REBOOTSTRAP_ENV) bash bin/nix-xd-log "$(SCOPE)" arm-rebootstrap bash arm/rebootstrap-podman.sh all

.PHONY: arm-purge-legacy-plan arm-purge-legacy
arm-purge-legacy-plan:
	@bash bin/nix-xd-log "$(SCOPE)" arm-purge-legacy-plan bash arm/purge-legacy.sh plan
arm-purge-legacy:
	@NIX_XD_LEGACY_PURGE_CONFIRM="$(LEGACY_PURGE_CONFIRM)" bash bin/nix-xd-log "$(SCOPE)" arm-purge-legacy bash arm/purge-legacy.sh apply

.PHONY: arm-inspect-legacy
arm-inspect-legacy:
	@bash bin/nix-xd-log "$(SCOPE)" arm-inspect-legacy bash arm/inspect-legacy.sh

.PHONY: arm-wind-down-plan arm-wind-down-stop
arm-wind-down-plan:
	@bash bin/nix-xd-log "$(SCOPE)" arm-wind-down-plan bash arm/wind-down.sh plan
arm-wind-down-stop:
	@bash bin/nix-xd-log "$(SCOPE)" arm-wind-down-stop bash arm/wind-down.sh stop

plan:
	@printf 'Host=%s Arch=%s System=%s Provider=%s Machine=%s Scope=%s Workspaces=%s Flake=%s%s\n' '$(OS)' '$(ARCH)' '$(NIX_SYSTEM)' '$(PROVIDER)' '$(MACHINE)' '$(SCOPE)' '$(WORKSPACES)' '$(FLAKE)' '$(TARGET)'

sync clone:
	@test -n "$(REPO)" || { echo "REPO=owner/repo required" >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" sync bash bin/nix-xd-sync "$(REPO)" "$(BRANCH)" "$(WORKSPACES)" "$(SYNC_NAME)" "$(REV)"

stage show check build path-info run:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-task "$@"

# Generic host-to-guest transport for an immutable, app-owned Nix package.
# Package output must contain guest.sh; the application defines its behavior.
GUEST_APP_REV ?=
ARGS_JSON ?= []
COREOS_KNOWN_HOSTS ?=
COREOS_GUEST_HOST ?= 127.0.0.1
export NIX_XD_GUEST_APP_REV = $(GUEST_APP_REV)
export NIX_XD_ARGS_JSON = $(ARGS_JSON)
export COREOS_KNOWN_HOSTS
export COREOS_GUEST_HOST
.PHONY: guest-app
guest-app:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-guest-app

# Generic host-side project action; project and action identities are caller-selected.
PROJECT ?=
APPLICATION ?=
ACTION ?=
PROJECT_REV ?=
export NIX_XD_PROJECT = $(PROJECT)
export NIX_XD_APPLICATION = $(APPLICATION)
export NIX_XD_ACTION = $(ACTION)
export NIX_XD_PROJECT_REV = $(PROJECT_REV)
export NIX_XD_HOST_WORKSPACES = $(WORKSPACES)
export NIX_XD_RUNTIME_REPO = $(CURDIR)
.PHONY: project-host-run
project-host-run:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-project-host-run

develop shell exec ps inspect store-info:
	@$(TASK) $@

# One read-only store report through the same provider/arch adapter and logger.
store-diagnose:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" store-diagnose bash bin/nix-xd-task store-diagnose

# Declarative GC roots are registered only inside the authoritative Nix-Alpine store.
store-roots-inspect store-roots-apply:
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_SYSTEM='$(NIX_SYSTEM)' STORE_ROOTS_FLAKE='$(COREOS_PROBE_FLAKE)' STORE_ROOTS_VOLUME='$(if $(COREOS_NIX_STORE_VOLUME),$(COREOS_NIX_STORE_VOLUME),$(STORE_VOLUME))' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-store-roots $(patsubst store-roots-%,%,$@)

# Qualifiers call Nix app outputs owned by the selected checkout.
# No claimed success when the selected output or host capability is missing.
compose:
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)compose)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

qualify:
ifeq ($(QUALIFY_APP),1)
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)qualify)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" MACHINE="$(MACHINE)" SCOPE="$(SCOPE)" ARCH="$(ARCH)"
else ifneq ($(QUALIFY_APP),0)
	@echo 'QUALIFY_APP must be 0 or 1' >&2; exit 2
endif
ifneq ($(strip $(MODULES)),)
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_SYSTEM='$(NIX_SYSTEM)' NIX_XD_QUALIFY_MODULES='$(MODULES)' bash bin/nix-xd-log "$(SCOPE)" qualify-modules bash qualifiers/dispatch.sh
endif

qualify-process:
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)qualify-process)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

qualify-service:
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)qualify-service)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

qualify-composition:
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)qualify-composition)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

qualify-plan:
	@test -n "$(PLAN_TARGET)" || { echo "PLAN_TARGET=#app required; no generic host runner assumed" >&2; exit 2; }
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(PLAN_TARGET)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

ifeq ($(PROVIDER),podman)
ifeq ($(OS),Darwin)
machine-init machine-check:
	@$(MACHINE_ENV) NIX_XD_MACHINE_VERIFY=1 bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-machine $(patsubst machine-%,%,$@)

machine-handoff machine-select:
	@NIX_XD_FROM_MACHINE="$(FROM_MACHINE)" NIX_XD_MACHINE="$(MACHINE)" NIX_XD_TRANSFER_IMAGE="$(TRANSFER_IMAGE)" bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-machine-handoff $(patsubst machine-%,%,$@)

machine-start:
	@state="$$(podman machine inspect "$(MACHINE)" --format '{{.State}}')"; \
	  if [[ "$$state" != running ]]; then podman machine start "$(MACHINE)"; fi
machine-stop:
	@podman machine stop "$(MACHINE)"
start: machine-start
	@podman machine ssh "$(MACHINE)" systemctl --user start "$(SCOPE).service"
stop:
	@podman machine ssh "$(MACHINE)" systemctl --user stop "$(SCOPE).service"
restart:
	@podman machine ssh "$(MACHINE)" systemctl --user restart "$(SCOPE).service"
status:
	@podman machine list
	@podman machine ssh "$(MACHINE)" systemctl --user --no-pager status "$(SCOPE).service"
logs:
	@podman machine ssh "$(MACHINE)" journalctl --user --no-pager -u "$(SCOPE).service" -n 100
else
machine-init machine-check machine-handoff machine-select:
	@echo "machine administration is macOS-only" >&2; exit 2
machine-start machine-stop:
	@echo 'Not needed on native Linux'
start:
	@systemctl --user start "$(SCOPE).service"
stop:
	@systemctl --user stop "$(SCOPE).service"
restart:
	@systemctl --user restart "$(SCOPE).service"
status:
	@systemctl --user --no-pager status "$(SCOPE).service"
logs:
	@journalctl --user --no-pager -u "$(SCOPE).service" -n 100
endif
image-build: machine-start
	@test "$(ARCH)" = arm64 || { echo "ARM Dockerfile requires ARCH=arm64" >&2; exit 2; }
	@podman --connection "$(MACHINE)" build --platform linux/arm64 -t "$(IMAGE)" ./arm
else ifeq ($(PROVIDER),container)
ifeq ($(OS),Darwin)
APPLE = NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-container
machine-init machine-check machine-handoff machine-select:
	@echo "Podman Machine is unavailable with PROVIDER=container" >&2; exit 2
machine-start machine-stop start stop restart status logs:
	@$(APPLE) $@
image-build:
	@$(APPLE) build
else
$(error PROVIDER=container requires macOS)
endif
else
$(error Unknown PROVIDER=$(PROVIDER))
endif

.PHONY: vm-state-preflight
VM_CONTAINER ?=
VM_INSTANCE ?=

vm-state-preflight:
	@NIX_XD_MACHINE='$(MACHINE)' bash bin/nix-xd-vm-state-preflight '$(VM_CONTAINER)' '$(VM_INSTANCE)'

# Generic declared workload storage grants; never reads volume payloads.
# Read-only validation of a declared future CoreOS 9P export.
.PHONY: guest-9p-runtime-qualify
guest-9p-runtime-qualify:
	@test "$(VMM)" = podman || { echo 'Guest 9P runtime gate requires Podman' >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-guest-9p-runtime-qualify

.PHONY: guest-9p-seed guest-9p-qualify
guest-9p-seed:
	@test -n "$(COREOS_9P_GRANTS_FILE)" || { echo 'GRANTS_FILE is required' >&2; exit 2; }
	@NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-guest-9p-seed

guest-9p-qualify:
	@test -n "$(COREOS_9P_GRANTS_FILE)" || { echo 'GRANTS_FILE is required' >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-guest-9p-qualify

.PHONY: guest-9p-plan guest-9p-preflight
guest-9p-plan guest-9p-preflight:
	@test -n "$(GRANTS_FILE)" || { echo 'GRANTS_FILE is required' >&2; exit 2; }
	@python3 lib/guest_9p_grants.py $(patsubst guest-9p-%,%,$@) "$(GRANTS_FILE)" --machine "$(MACHINE)"

.PHONY: grants-isolation-qualify
grants-isolation-qualify:
	@NIX_XD_MACHINE="$(MACHINE)" NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-grants-isolation-qualify

.PHONY: grants-host-share-qualify
grants-host-share-qualify:
	@NIX_XD_MACHINE="$(MACHINE)" NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-grants-host-share-qualify

PROGRAM ?=
BUILD_APP ?=
RUN_PACKAGE ?=
CREDENTIAL_IDENTITY ?=
CREDENTIAL_KNOWN_HOSTS ?=
CREDENTIAL_RECONCILE ?= 0
GUEST_SSH_PORT ?= 2222
export NIX_XD_CREDENTIAL_IDENTITY = $(CREDENTIAL_IDENTITY)
export NIX_XD_CREDENTIAL_KNOWN_HOSTS = $(CREDENTIAL_KNOWN_HOSTS)
export NIX_XD_CREDENTIAL_RECONCILE = $(CREDENTIAL_RECONCILE)
export NIX_XD_BUILD_APP = $(BUILD_APP)
export NIX_XD_RUN_PACKAGE = $(RUN_PACKAGE)
export NIX_XD_GUEST_SSH_PORT = $(GUEST_SSH_PORT)
.PHONY: grants-credentials-import grants-transport-qualify
grants-credentials-import:
	@test "$(PROVIDER)" = podman || { echo 'Podman provider required' >&2; exit 2; }
	@test -n "$(GRANTS_FILE)" -a -n "$(CREDENTIAL_IDENTITY)" -a -n "$(CREDENTIAL_KNOWN_HOSTS)" || { echo 'GRANTS_FILE and both credential paths are required' >&2; exit 2; }
	@$(TASK_ENV) NIX_XD_IMAGE='$(IMAGE)' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-grants-import-credentials

grants-transport-qualify:
	@test "$(PROVIDER)" = podman || { echo 'Podman provider required' >&2; exit 2; }
	@test -n "$(GRANTS_FILE)" -a -n "$(FLAKE)" -a -n "$(BUILD_APP)" -a -n "$(RUN_PACKAGE)" -a -n "$(PROGRAM)" || { echo 'Select grants, flake, native build app, run package and program' >&2; exit 2; }
	@$(TASK_ENV) NIX_XD_IMAGE='$(IMAGE)' NIX_XD_PROGRAM='$(PROGRAM)' NIX_XD_STORE_VOLUME='$(SCOPE)-store' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-grants-transport-qualify

.PHONY: grants-execute
grants-execute:
	@test "$(PROVIDER)" = podman || { echo 'Rootless Podman provider required' >&2; exit 2; }
	@test -n "$(GRANTS_FILE)" -a -n "$(PROGRAM)" -a -n "$(TARGET)" || { echo 'GRANTS_FILE, PROGRAM and TARGET are required' >&2; exit 2; }
	@$(TASK_ENV) NIX_XD_IMAGE='$(IMAGE)' NIX_XD_PROGRAM='$(PROGRAM)' NIX_XD_STORE_VOLUME='$(SCOPE)-store' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-grants-execute

.PHONY: grants-plan grants-render grants-verify
grants-plan grants-render:
	@test -n "$(GRANTS_FILE)" || { echo 'GRANTS_FILE is required' >&2; exit 2; }
	@python3 lib/runtime_grants.py $(patsubst grants-%,%,$@) "$(GRANTS_FILE)"
grants-verify:
	@test -n "$(GRANTS_FILE)" || { echo 'GRANTS_FILE is required' >&2; exit 2; }
	@python3 lib/runtime_grants.py verify "$(GRANTS_FILE)" --machine "$(MACHINE)" --scope "$(SCOPE)"

.PHONY: state-volume-plan state-volume-provision state-volume-inspect state-volume-export
STATE_KIND ?= control
STATE_NAME ?=
STATE_EXPORT_PATH ?=
STATE_VOLUME_ARGS = NIX_XD_MACHINE='$(MACHINE)' bash bin/nix-xd-state-volume

state-volume-plan state-volume-provision state-volume-inspect:
	@$(STATE_VOLUME_ARGS) $(patsubst state-volume-%,%,$@) '$(STATE_KIND)' '$(STATE_NAME)'

state-volume-export:
	@$(STATE_VOLUME_ARGS) export '$(STATE_KIND)' '$(STATE_NAME)' '$(STATE_EXPORT_PATH)'

.PHONY: storage-review
storage-review:
	@bash bin/nix-xd-storage-review "$(MACHINE)"

.PHONY: check-static-internal
check-static:
	@bash bin/nix-xd-log "$(SCOPE)" check-static $(MAKE) --no-print-directory check-static-internal

check-static-internal:
	@python3 tests/ghxd-source-version.py
	@python3 tests/tenant-storage.py
	@python3 tests/bootstrap-profile.py
	@bash tests/workspace-contract.sh
	@python3 tests/fatline-host-link.py
	@python3 tests/fatline-multivm.py
	@python3 tests/fatline-recovery.py
	@python3 tests/fatline-reboot.py
	@python3 tests/fatline-rebootstrap.py
	@python3 tests/fatline-generations.py
	@python3 tests/fatline-profile.py
	@python3 tests/fatline-logmash.py
	@python3 tests/composition-artifact.py
	@bash tests/project-host-run-contract.sh
	@python3 tests/runtime-grants.py
	@python3 tests/guest-9p-grants.py
	@bash -n bin/nix-xd-grants-host-share-qualify
	@bash -n bin/nix-xd-grants-isolation-qualify runtime/grants-isolation-qualify.sh
	@bash -n bin/nix-xd-coreos-podman
	@bash -n bin/nix-xd-guest-9p-seed bin/nix-xd-guest-9p-qualify
	@bash -n bin/nix-xd-guest-9p-runtime-qualify
	@bash -n bin/nix-xd-grants-execute
	@bash -n bin/nix-xd-grants-import-credentials bin/nix-xd-grants-transport-qualify
	@bash -n bin/nix-xd-ghxd-inventory
	@bash -n bin/nix-xd-ghxd
	@bash tests/grants-transport-contract.sh
	@bash tests/grants-execute-contract.sh
	@python3 tests/fatline-services.py
	@bash -n bin/nix-xd-guest-app
	@python3 tests/builder-stores.py
	@python3 tests/builder-store-profile.py
	@bash -n bin/nix-xd-builder-store-profile bin/nix-xd-builder-store-idempotence bin/nix-xd-builder-store-qualify-fresh bin/nix-xd-builder-store-maintenance
	@python3 tests/wisp-go-owner.py
	@python3 tests/nix-task-contract.py
	@python3 tests/agni-coreos-plan.py
	@python3 tests/redis-application.py
	@bash -n qualifiers/redis-application.sh
	@bash tests/project-run-contract.sh
	@python3 tests/chroot-attach.py
	@python3 tests/runtime-primitives.py
	@bash tests/runtime-resource-contract.sh
	@python3 tests/compositions.py
	@python3 tests/guest-executor.py
	@python3 tests/coreos-managed-start.py
	@python3 tests/workload-transport.py
	@python3 tests/workloads.py
	@bash -n bin/nix-xd-workload bin/nix-xd-workload-start bin/nix-xd-workload-qualify
	@bash tests/store-roots-contract.sh
	@bash tests/store-diagnose-contract.sh
	@bash -n bin/nix-xd-qualify-starwisp-shared bin/nix-xd-bootstrap-amd64 qualifiers/dispatch.sh qualifiers/modules/secrets.sh arm/purge-legacy.sh arm/inspect-legacy.sh arm/wind-down.sh arm/qualify-recreation-podman.sh arm/rebootstrap-podman.sh arm/init-nix-store.sh arm/bootstrap-macos.sh arm/bootstrap-podman.sh arm/bootstrap-container.sh bin/nix-xd-container bin/nix-xd-machine bin/nix-xd-machine-handoff bin/nix-xd-store-export-check bin/nix-xd-qualify-starwisp bin/nix-xd-task bin/nix-xd-sync bin/nix-xd-log bin/nix-xd-coreos-hvf bin/nix-xd-coreos-podman bin/nix-xd-wisp-ssh bin/nix-xd-guest-store-exec
	@$(MAKE) --no-print-directory -n PROVIDER=podman OS=Linux plan sync stage build show qualify-process >/dev/null
	@$(MAKE) --no-print-directory -n PROVIDER=container OS=Darwin plan bootstrap stage build show qualify-composition >/dev/null
	@bash tests/bootstrap-architecture-contract.sh
	@bash tests/qualification-modules.sh
	@bash tests/machine-contract.sh
	@bash tests/starwisp-shared-contract.sh
	@bash tests/starwisp-lifecycle.sh
	@echo 'Static command checks passed; no ARM runtime executed.'

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

# Shared post-bootstrap lifecycle. VM provisioning remains in the CoreOS adapter.
WORKLOAD ?= starwisp-probe
WORKLOAD_FLAKE ?= /workspaces/nix.xd
WORKLOAD_REV ?= $(shell git rev-parse HEAD)
WORKLOAD_GENERATION ?=
export NIX_XD_PROVIDER = $(PROVIDER)
export NIX_XD_SYSTEM = $(NIX_SYSTEM)
export NIX_XD_WORKLOAD = $(WORKLOAD)
export NIX_XD_WORKLOAD_FLAKE = $(WORKLOAD_FLAKE)
export NIX_XD_WORKLOAD_REV = $(WORKLOAD_REV)
COMPOSITION_FLAKE ?=
COMPOSITION_REV ?=
export NIX_XD_COMPOSITION_FLAKE = $(COMPOSITION_FLAKE)
export NIX_XD_COMPOSITION_REV = $(COMPOSITION_REV)
ARTIFACT_FLAKE ?=
export NIX_XD_ARTIFACT_FLAKE = $(ARTIFACT_FLAKE)

export NIX_XD_WORKLOAD_GENERATION = $(WORKLOAD_GENERATION)
.PHONY: workload-prepare workload-inspect workload-activate workload-check workload-status workload-stop
workload-prepare workload-inspect workload-activate workload-check workload-status workload-stop:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workload $(patsubst workload-%,%,$@)

.PHONY: workload-qualify
workload-qualify:
	@test "$(ARCH)" = arm64 && test "$(PROVIDER)" = podman && test "$(VMM)" = podman || { echo 'Current CoreOS VM adapter requires ARM64 Podman Machine' >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" workload-prepare bash bin/nix-xd-workload prepare
	@NIX_XD_QUALIFY_WORKLOAD=1 COREOS_NIX_STORE_VOLUME='$(SCOPE)-store' bash bin/nix-xd-log "$(SCOPE)" workload-qualify bash bin/nix-xd-qualify-starwisp

.PHONY: workload-start workload-shell
workload-start:
	@bash bin/nix-xd-log "$(SCOPE)" workload-start bash bin/nix-xd-workload-start

# Preserve the terminal and avoid logging interactive shell content.
workload-shell:
	@bash bin/nix-xd-workload shell

.PHONY: workload-recreate workload-qualify-recreation workload-recreate-abandon
workload-recreate workload-qualify-recreation:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workload recreate
workload-recreate-abandon:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workload recreate-abandon

# Flake-composed sandbox phases; each can be run independently.
PYTHON ?= python3
PROFILE_MODE ?= store
export NIX_XD_PROFILE_MODE = $(PROFILE_MODE)
PROFILE_SAMPLES ?= 1
export NIX_XD_PROFILE_SAMPLES = $(PROFILE_SAMPLES)
COMPOSITION ?= shared-store-matrix
export NIX_XD_COMPOSITION = $(COMPOSITION)
.PHONY: composition-plan composition-prepare composition-start composition-status composition-qualify composition-stop composition-cancel composition-profile composition-application
composition-plan composition-prepare composition-start composition-status composition-qualify composition-stop composition-cancel composition-profile composition-application:
	@command -v "$(PYTHON)" >/dev/null || { echo 'Composition qualification requires host Python 3.9+; select PYTHON=/path/to/python3. Bootstrap does not require Python.' >&2; exit 2; }
	@"$(PYTHON)" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Composition qualification requires Python 3.9+")'
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/compose_runtime.py $(patsubst composition-%,%,$@)

# One shareable log covers static checks, staging, and every runtime phase.
.PHONY: composition-local composition-local-phases
composition-local:
	@bash bin/nix-xd-log "$(SCOPE)" composition-local $(MAKE) --no-print-directory composition-local-phases

composition-local-phases:
	@$(MAKE) --no-print-directory -j1 -S check-static stage composition-plan composition-prepare composition-start composition-qualify composition-status WORKSPACES="$(abspath $(CURDIR)/..)" CHECKOUT="$(notdir $(CURDIR))"

# Source-built optional Wisp tooling; application controllers are isolated.
WISP_SMOKE_REV ?= 66950da9a5e4e5303f5dcd018f9039f9b6fc8496
.PHONY: wisp-go-build wisp-go-check wisp-go-qualify wisp-go-forward
wisp-go-build wisp-go-check wisp-go-qualify wisp-go-forward:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-wisp-go $(patsubst wisp-go-%,%,$@)

# Validate an explicitly selected pinned GHXD source manifest.
GHXD_SOURCE_MANIFEST ?=
.PHONY: ghxd-source-version-check
ghxd-source-version-check:
	@test -n "$(GHXD_SOURCE_MANIFEST)" || { echo 'GHXD_SOURCE_MANIFEST is required' >&2; exit 2; }
	@python3 lib/ghxd_source_version.py "$(GHXD_SOURCE_MANIFEST)"

# Persistent builder store selection; peer aliases map to /peer/<alias>:ro.
STORE_VOLUME ?= $(SCOPE)-store
PEER_STORES ?=
export NIX_XD_STORE_VOLUME = $(STORE_VOLUME)
export NIX_XD_PEER_STORES = $(PEER_STORES)
.PHONY: builder-store-plan
builder-store-plan:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-store-plan

PEER_BUILDER_SCOPE ?= nix-xd-grumble
PEER_BUILDER_VOLUME ?= $(PEER_BUILDER_SCOPE)-store
PEER_BUILDER_ALIAS ?= agni
export NIX_XD_PEER_BUILDER_SCOPE = $(PEER_BUILDER_SCOPE)
export NIX_XD_PEER_BUILDER_VOLUME = $(PEER_BUILDER_VOLUME)
export NIX_XD_PEER_BUILDER_ALIAS = $(PEER_BUILDER_ALIAS)
.PHONY: builder-store-qualify
builder-store-qualify:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/builder_store_qualify.py

# Application-specific historical controllers are available only for explicit
# recovery of old qualified generations. They are not part of the default API.
ENABLE_LEGACY_APPLICATION_CONTROLLERS ?= 0
ifeq ($(ENABLE_LEGACY_APPLICATION_CONTROLLERS),1)
include mk/legacy-application-controllers.mk
else ifneq ($(ENABLE_LEGACY_APPLICATION_CONTROLLERS),0)
$(error ENABLE_LEGACY_APPLICATION_CONTROLLERS must be 0 or 1)
endif

# Make selects the runtime and project; orchestration executes in Nix-Alpine.
PROJECT_FLAKE ?=
PROJECT_APP ?= default
PROJECT_ARGS_JSON ?= []
PROJECT_RUNTIME_FLAKE ?= $(WORKLOAD_FLAKE)
export NIX_XD_PROJECT_FLAKE = $(PROJECT_FLAKE)
export NIX_XD_PROJECT_APP = $(PROJECT_APP)
export NIX_XD_PROJECT_ARGS_JSON = $(PROJECT_ARGS_JSON)
export NIX_XD_PROJECT_RUNTIME_FLAKE = $(PROJECT_RUNTIME_FLAKE)
.PHONY: project-run
project-run:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-task project-run

PROJECT_STORE ?= local
CHROOT_NAME ?= grumble
CHROOT_VOLUME ?= $(SCOPE)-$(CHROOT_NAME)-chroot
export NIX_XD_PROJECT_STORE = $(PROJECT_STORE)
export NIX_XD_CHROOT_NAME = $(CHROOT_NAME)
export NIX_XD_CHROOT_VOLUME = $(CHROOT_VOLUME)
.PHONY: chroot-store-attach chroot-store-qualify
chroot-store-attach:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-chroot-attach
chroot-store-qualify:
	@$(MAKE) --no-print-directory project-run PROJECT_FLAKE="$(WORKLOAD_FLAKE)" PROJECT_APP=chroot-store-poc PROJECT_ARGS_JSON='["--root","/stores/$(CHROOT_NAME)","--flake","$(WORKLOAD_FLAKE)","--system","$(NIX_SYSTEM)"]' PROJECT_STORE=local

.PHONY: builder-chroot-profile
builder-chroot-profile:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-profile

.PHONY: builder-chroot-diagnose
builder-chroot-diagnose:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-profile diagnose

CHROOT_SELINUX ?= keep
export NIX_XD_CHROOT_SELINUX = $(CHROOT_SELINUX)

.PHONY: builder-chroot-syscalls
builder-chroot-syscalls:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-builder-profile syscalls

# Declarative, opt-in post-bootstrap profile for alternate writable Nix stores.
include mk/builder-store-profile.mk

# Independent authoritative-store writers (distinct Nix-Alpine scopes).
# Separate from the multi-chroot profile inside one builder.
ISOLATION_PRIMARY ?= nix-xd-arm
ISOLATION_SECONDARY ?= nix-xd-grumble-arm
.PHONY: store-isolation-check store-isolation-static
store-isolation-check:
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' \
	  NIX_XD_ISOLATION_PRIMARY='$(ISOLATION_PRIMARY)' \
	  NIX_XD_ISOLATION_SECONDARY='$(ISOLATION_SECONDARY)' \
	  bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-store-isolation

store-isolation-static:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash tests/store-isolation-contract.sh

.PHONY: workspace-inventory
workspace-inventory:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workspace-inventory

# Consolidated store-contract check and maintenance inventory.
.PHONY: nix-store-check maintenance-review
nix-store-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory nix-store-check-internal

.PHONY: nix-store-check-internal
nix-store-check-internal:
	@bash -n bin/nix-xd-vm-state-preflight
	@bash tests/state-volume-contract.sh
	@bash -n bin/nix-xd-workspace-inventory bin/nix-xd-store-isolation
	@$(MAKE) --no-print-directory builder-store-profile-check-internal
	@bash tests/store-isolation-contract.sh
	@echo 'NIX_STORE_STATIC_RESULT=passed'

maintenance-review:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory maintenance-review-internal

.PHONY: maintenance-review-internal
maintenance-review-internal:
	@bash bin/nix-xd-workspace-inventory
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_MACHINE='$(MACHINE)' \
	  NIX_XD_QUALIFY_SCOPE='$(QUALIFY_STORE_SCOPE)' \
	  NIX_XD_QUALIFY_IMAGE='$(QUALIFY_STORE_IMAGE)' \
	  bash bin/nix-xd-builder-store-maintenance inventory
	@echo 'MAINTENANCE_REVIEW_RESULT=passed mutations=false'

# Generic resource identity and host artifacts; no application policy.
LIFECYCLE ?= reusable
COMPOSITION_ID ?= infrastructure
PLACEMENT_ID ?= host
ARTIFACT_ROOT ?= $(CURDIR)/.artifacts
export NIX_XD_LIFECYCLE = $(LIFECYCLE)
export NIX_XD_COMPOSITION_ID = $(COMPOSITION_ID)
export NIX_XD_PLACEMENT_ID = $(PLACEMENT_ID)
export NIX_XD_ARTIFACT_ROOT = $(ARTIFACT_ROOT)
export NIX_XD_ARTIFACT_COMPOSITION = $(COMPOSITION_ID)
export NIX_XD_ARTIFACT_PLACEMENT = $(PLACEMENT_ID)
.PHONY: runtime-inventory image-export runtime-contract-check
runtime-inventory:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-runtime-inventory
image-export:
	@$(TASK_ENV) NIX_XD_IMAGE='$(IMAGE)' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-image-export
runtime-contract-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash tests/runtime-resource-contract.sh

include mk/workspace.mk

TENANT_STORAGE_SCOPE ?= $(SCOPE)-storage-qualify
export NIX_XD_TENANT_SCOPE = $(TENANT_STORAGE_SCOPE)
export NIX_XD_TENANT_IMAGE = $(IMAGE)
.PHONY: tenant-storage-check tenant-storage-qualify
tenant-storage-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory tenant-storage-check-internal
.PHONY: tenant-storage-check-internal
tenant-storage-check-internal:
	@bash -n lib/tenant-storage.sh bin/nix-xd-tenant-storage-qualify runtime/tenant-storage-qualify.sh
	@python3 tests/tenant-storage.py
tenant-storage-qualify:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory tenant-storage-qualify-internal
.PHONY: tenant-storage-qualify-internal
tenant-storage-qualify-internal:
	@$(MAKE) --no-print-directory tenant-storage-check-internal
	@bash bin/nix-xd-tenant-storage-qualify
