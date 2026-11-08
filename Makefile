# Generic Nix-Alpine orchestration; applications supply their own flakes and gates.
SHELL := /bin/bash
.DEFAULT_GOAL := help

PROVIDER ?= podman
MACHINE ?= podman-machine-default
MACHINE_PROVIDER ?= applehv
MACHINE_CPUS ?= 6
MACHINE_MEMORY_MIB ?= 8192
MACHINE_DISK_GIB ?= 120
MACHINE_DEFAULT ?= 0
MACHINE_BOOTSTRAP ?= 1
MACHINE_VERIFY ?= 0
MACHINE_ENV = NIX_XD_MACHINE="$(MACHINE)" NIX_XD_MACHINE_PROVIDER="$(MACHINE_PROVIDER)" NIX_XD_MACHINE_CPUS="$(MACHINE_CPUS)" NIX_XD_MACHINE_MEMORY_MIB="$(MACHINE_MEMORY_MIB)" NIX_XD_MACHINE_DISK_GIB="$(MACHINE_DISK_GIB)" NIX_XD_MACHINE_DEFAULT="$(MACHINE_DEFAULT)" NIX_XD_MACHINE_BOOTSTRAP="$(MACHINE_BOOTSTRAP)" NIX_XD_MACHINE_VERIFY="$(MACHINE_VERIFY)"
SCOPE ?= nix-xd-arm
IMAGE ?= localhost/nix-xd:arm64
WORKSPACES ?= $(abspath $(CURDIR))
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

TASK_ENV = NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SYSTEM='aarch64-linux' NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_WORKSPACES='$(WORKSPACES)' NIX_XD_CHECKOUT='$(CHECKOUT)' NIX_XD_FLAKE='$(FLAKE)' NIX_XD_TARGET='$(TARGET)' NIX_XD_ARGS='$(ARGS)' NIX_XD_CMD='$(CMD)' 
TASK = $(TASK_ENV) bash bin/nix-xd-task

.PHONY: help bootstrap plan image-build machine-init machine-check machine-start machine-stop start stop restart status logs shell exec ps inspect store-info sync clone stage show check build path-info run develop compose qualify qualify-process qualify-service qualify-composition qualify-plan check-static

help:
	@printf '%s\n' \
	  'make bootstrap PROVIDER=podman|container       Bootstrap ARM host (default podman)' \
	  'make machine-init MACHINE=... MACHINE_MEMORY_MIB=8192 MACHINE_CPUS=6 MACHINE_DISK_GIB=120' \
	  'make machine-check MACHINE=... (enforce minimum requested VM resources)' \
	  'make image-build                            Build Nix-Alpine OCI image' \
	  'make sync REPO=owner/repo BRANCH=... [REV=sha] [SYNC_NAME=path]' \
	  'make stage CHECKOUT=path                     Stage committed checkout at /workspaces/path' \
	  'make show|check|build|path-info FLAKE=path TARGET=$(HASH)output' \
	  'make run FLAKE=path TARGET=\x23app ARGS="..."' \
	  'make compose|qualify|qualify-process|qualify-service|qualify-composition' \
	  'make qualify-plan FLAKE=path PLAN_TARGET=\x23app (application-owned plan)' \
	  'make start|stop|restart|status|logs|shell|exec|ps|inspect|store-info' \
	  'make check-static                            Host-independent static checks'

bootstrap:
	@test "$(OS)" = Darwin || { echo "macOS bootstrap requires Darwin" >&2; exit 1; }
	@NIX_XD_PROVIDER="$(PROVIDER)" $(MACHINE_ENV) NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-log "$(SCOPE)" bootstrap bash arm/bootstrap-macos.sh

plan:
	@printf 'Host=%s Provider=%s Machine=%s Scope=%s Workspaces=%s Flake=%s%s\n' '$(OS)' '$(PROVIDER)' '$(MACHINE)' '$(SCOPE)' '$(WORKSPACES)' '$(FLAKE)' '$(TARGET)'

sync clone:
	@test -n "$(REPO)" || { echo "REPO=owner/repo required" >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" sync bash bin/nix-xd-sync "$(REPO)" "$(BRANCH)" "$(WORKSPACES)" "$(SYNC_NAME)" "$(REV)"

stage show check build path-info run:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-task "$@"

develop shell exec ps inspect store-info:
	@$(TASK) $@

# Qualifiers call Nix app outputs owned by the selected checkout.
# No claimed success when the selected output or host capability is missing.
compose:
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)compose)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

qualify:
	@$(MAKE) --no-print-directory run FLAKE="$(FLAKE)" TARGET="$(if $(TARGET),$(TARGET),$(HASH)qualify)" ARGS="$(ARGS)" PROVIDER="$(PROVIDER)" SCOPE="$(SCOPE)"

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
machine-init machine-check:
	@echo "machine-init/check are macOS-only" >&2; exit 2
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
	@podman build --platform linux/arm64 -t "$(IMAGE)" ./arm
else ifeq ($(PROVIDER),container)
ifeq ($(OS),Darwin)
APPLE = NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-container
machine-init machine-check:
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

check-static:
	@bash -n arm/bootstrap-macos.sh arm/bootstrap-podman.sh arm/bootstrap-container.sh bin/nix-xd-container bin/nix-xd-machine bin/nix-xd-task bin/nix-xd-sync bin/nix-xd-log bin/nix-xd-coreos-hvf bin/nix-xd-coreos-podman bin/nix-xd-wisp-ssh
	@$(MAKE) --no-print-directory -n PROVIDER=podman OS=Linux plan sync stage build show qualify-process >/dev/null
	@$(MAKE) --no-print-directory -n PROVIDER=container OS=Darwin plan bootstrap stage build show qualify-composition >/dev/null
	@bash tests/machine-contract.sh
	@echo 'Static command checks passed; no ARM runtime executed.'

# Host-side accelerated CoreOS qualification is intentionally independent of the
# selected Nix execution provider. Artifacts must be exported before boot.
PROFILE ?= starwisp
COREOS_STATE_ROOT ?= $(CURDIR)/.state/coreos
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
VMM ?= podman
COREOS_FLAKE ?= /workspaces/agni/qemu/coreos-live/local
COREOS_RUNNER_IMAGE ?= localhost/agni-coreos-qemu-runner:44.20261023.3.1-aarch64
COREOS_HOST_ENV = NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' COREOS_FLAKE='$(COREOS_FLAKE)' COREOS_RUNNER_IMAGE='$(COREOS_RUNNER_IMAGE)' COREOS_VMM='$(VMM)' COREOS_PROFILE='$(PROFILE)' COREOS_STATE_ROOT='$(COREOS_STATE_ROOT)' COREOS_IMAGE='$(COREOS_IMAGE)' COREOS_IMAGE_SHA256='$(COREOS_IMAGE_SHA256)' COREOS_IGNITION='$(COREOS_IGNITION)' COREOS_FIRMWARE='$(COREOS_FIRMWARE)' COREOS_SSH_PORT='$(COREOS_SSH_PORT)' COREOS_RAM_MIB='$(COREOS_RAM_MIB)' COREOS_CPUS='$(COREOS_CPUS)' COREOS_GUEST_USER='$(COREOS_GUEST_USER)' COREOS_SSH_KEY='$(COREOS_SSH_KEY)' COREOS_SSH_PUBLIC_KEY='$(COREOS_SSH_PUBLIC_KEY)'

.PHONY: coreos-container-build coreos-ignition-build coreos-preflight coreos-boot coreos-stop coreos-qualify coreos-reset-failed
coreos-container-build:
	@test "$(VMM)" = podman || { echo 'coreos-container-build requires VMM=podman' >&2; exit 2; }
	@$(COREOS_HOST_ENV) bash bin/nix-xd-log "$(SCOPE)" coreos-container-build bash bin/nix-xd-coreos-podman build

coreos-ignition-build:
	@test "$(VMM)" = podman || { echo 'coreos-ignition-build requires VMM=podman' >&2; exit 2; }
	@$(COREOS_HOST_ENV) bash bin/nix-xd-log "$(SCOPE)" coreos-ignition-build bash bin/nix-xd-coreos-podman ignition

coreos-reset-failed:
	@test "$(VMM)" = podman || { echo "coreos-reset-failed requires VMM=podman" >&2; exit 2; }
	@$(COREOS_HOST_ENV) bash bin/nix-xd-log "$(SCOPE)" coreos-reset-failed bash bin/nix-xd-coreos-podman reset-failed

coreos-preflight coreos-boot coreos-stop:
	@case "$(VMM)" in \
	  podman) $(COREOS_HOST_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-coreos-podman $(patsubst coreos-%,%,$@) ;; \
	  hvf) $(COREOS_HOST_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-coreos-hvf $(patsubst coreos-%,%,$@) ;; \
	  *) echo 'VMM must be podman or hvf' >&2; exit 2 ;; \
	  esac

coreos-qualify:
	@$(COREOS_HOST_ENV) bash bin/nix-xd-log "$(SCOPE)" coreos-qualify bash bin/nix-xd-wisp-ssh
