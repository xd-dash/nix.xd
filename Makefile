# Generic Nix-Alpine orchestration; applications supply their own flakes and gates.
SHELL := /bin/bash
.DEFAULT_GOAL := help

PROVIDER ?= podman
MACHINE ?= podman-machine-default
SCOPE ?= nix-xd-smoke-podman
IMAGE ?= localhost/nix-xd:arm64
WORKSPACES ?= $(abspath $(CURDIR))
WORKSPACE_MODE ?= bind
WORKSPACE_ACCESS ?= rw
AGE_VOLUME ?=
AGE_ACCESS ?= ro
GITHUB_CLIENT_ID ?=
SMOKE_SOURCE ?=
SMOKE_ACCESS ?= readwrite
EXCHANGE_ROOT ?=
EXCHANGE_ACCESS ?= readwrite
READER_SCOPE ?=
STORE_PATH ?=
LINUX_SYSTEM ?= aarch64-linux
NIX_ALPINE_REV ?= fcd480320c3d0c1f8edf5117095dba7751c52e4a
NIX_ALPINE_CHECKOUT ?= nix-alpine/nix-alpine
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
PLAN_REPO ?=
PLAN_BRANCH ?= main
PLAN_REV ?=
PLAN_CHECKOUT ?=
PLAN_FILE ?=
PLAN_FLAKE ?=
PLAN_TARGET ?= qualify-plan
PLAN_GATE ?= all
PLAN_SOURCES ?=
PLAN_ARTIFACT_MANIFEST ?=
PLAN_CAPABILITIES ?=
RETAIN ?= 0
OS := $(shell uname -s)

TASK_ENV = NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SYSTEM='$(LINUX_SYSTEM)' NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_WORKSPACES='$(WORKSPACES)' NIX_XD_WORKSPACE_MODE='$(WORKSPACE_MODE)' NIX_XD_CHECKOUT='$(CHECKOUT)' NIX_XD_FLAKE='$(FLAKE)' NIX_XD_TARGET='$(TARGET)' NIX_XD_ARGS='$(ARGS)' NIX_XD_CMD='$(CMD)' 
TASK = $(TASK_ENV) bash bin/nix-xd-task

.PHONY: help bootstrap plan image-build machine-start machine-stop start stop restart status logs shell exec ps inspect store-info sync clone stage show check build path-info run develop compose qualify qualify-process qualify-service qualify-composition qualify-plan qualify-smoke qualify-ghxd qualify-ghxd-auth ghxd-auth ghxd-token-check age-setup smoke workspace-check refresh inventory store-export store-import share-check check-static

help:
	@printf '%s\n' \
	  'make bootstrap PROVIDER=podman                  Canonical Linux Quadlet inside Podman Machine' \
	  'make refresh PROVIDER=podman                    Rebuild pinned toolbox; preserve store' \
	  'make inventory                                  Read-only Podman/Apple resource inventory' \
	  'make image-build                            Build Nix-Alpine OCI image' \
	  'WORKSPACE_MODE=bind|staged                  Bind mount is default for new runners' \
	  'make sync REPO=owner/repo BRANCH=... [REV=sha] [SYNC_NAME=path]' \
	  'make stage CHECKOUT=path                     Legacy snapshot mode only; bind mode needs no staging' \
	  'make show|check|build|path-info FLAKE=path TARGET=$(HASH)output' \
	  'make run FLAKE=path TARGET=$(HASH)app ARGS="..."' \
	  'make compose|qualify|qualify-process|qualify-service|qualify-composition' \
	  'make qualify-plan PLAN_REPO=... PLAN_REV=... PLAN_CHECKOUT=... PLAN_FILE=... PLAN_FLAKE=...' \
	  'make start|stop|restart|status|logs|shell|exec|ps|inspect|store-info' \
	  'make smoke PROVIDER=container               Legacy Apple runtime probe (rollback only)' \
	  'make workspace-check PROVIDER=podman        Verify VM mount, keep-id, persistent /nix' \
	  'make qualify-smoke PROVIDER=podman         Full logged Smoke test, build and refresh qualification' \
	  'make qualify-ghxd                        Two-runner Go cache, Nix, SOPS/age qualification' \
	  'make store-export STORE_PATH=/nix/store/...  Publish closure in mounted workspace cache' \
	  'make store-import STORE_PATH=/nix/store/...  Import closure into isolated Nix store' \
	  'make share-check READER_SCOPE=...            Legacy Apple VM sharing diagnostic' \
	  'make check-static                            Host-independent static checks'

bootstrap:
	@test "$(OS)" = Darwin || { echo "macOS bootstrap requires Darwin" >&2; exit 1; }
	@NIX_XD_PROVIDER="$(PROVIDER)" NIX_XD_MACHINE="$(MACHINE)" NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" NIX_XD_WORKSPACES="$(WORKSPACES)" NIX_ALPINE_REV="$(NIX_ALPINE_REV)" NIX_ALPINE_CHECKOUT="$(NIX_ALPINE_CHECKOUT)" NIX_XD_WORKSPACE_MODE="$(WORKSPACE_MODE)" NIX_XD_WORKSPACE_ACCESS="$(WORKSPACE_ACCESS)" NIX_XD_AGE_VOLUME="$(AGE_VOLUME)" NIX_XD_AGE_ACCESS="$(AGE_ACCESS)" NIX_XD_SMOKE_SOURCE="$(SMOKE_SOURCE)" NIX_XD_SMOKE_ACCESS="$(SMOKE_ACCESS)" NIX_XD_EXCHANGE_ROOT="$(EXCHANGE_ROOT)" NIX_XD_EXCHANGE_ACCESS="$(EXCHANGE_ACCESS)" bash bin/nix-xd-log "$(SCOPE)" bootstrap bash arm/bootstrap-macos.sh

plan:
	@printf 'Host=%s Provider=%s Machine=%s Scope=%s Workspaces=%s Flake=%s%s\n' '$(OS)' '$(PROVIDER)' '$(MACHINE)' '$(SCOPE)' '$(WORKSPACES)' '$(FLAKE)' '$(TARGET)'

sync clone:
	@test -n "$(REPO)" || { echo "REPO=owner/repo required" >&2; exit 2; }
	@bash bin/nix-xd-log "$(SCOPE)" sync bash bin/nix-xd-sync "$(REPO)" "$(BRANCH)" "$(WORKSPACES)" "$(SYNC_NAME)" "$(REV)"

stage show check build path-info run:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-task "$@"

develop shell ps inspect store-info:
	@$(TASK) $@

exec:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" exec bash bin/nix-xd-task exec

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

PLAN_ENV = NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_WORKSPACES='$(WORKSPACES)' NIX_XD_WORKSPACE_MODE='$(WORKSPACE_MODE)' NIX_XD_SYSTEM='$(LINUX_SYSTEM)' NIX_ALPINE_REV='$(NIX_ALPINE_REV)' NIX_ALPINE_CHECKOUT='$(NIX_ALPINE_CHECKOUT)' PLAN_REPO='$(PLAN_REPO)' PLAN_BRANCH='$(PLAN_BRANCH)' PLAN_REV='$(PLAN_REV)' PLAN_CHECKOUT='$(PLAN_CHECKOUT)' PLAN_FILE='$(PLAN_FILE)' PLAN_FLAKE='$(PLAN_FLAKE)' PLAN_TARGET='$(PLAN_TARGET)' PLAN_GATE='$(PLAN_GATE)' PLAN_SOURCES='$(PLAN_SOURCES)' PLAN_ARTIFACT_MANIFEST='$(PLAN_ARTIFACT_MANIFEST)' PLAN_CAPABILITIES='$(PLAN_CAPABILITIES)' RETAIN='$(RETAIN)'

qualify-plan:
	@$(PLAN_ENV) bash bin/nix-xd-log "$(SCOPE)" qualify-plan bash bin/nix-xd-plan

smoke:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" smoke bash bin/nix-xd-smoke

refresh:
	@$(MAKE) --no-print-directory bootstrap PROVIDER="$(PROVIDER)" MACHINE="$(MACHINE)" SCOPE="$(SCOPE)" WORKSPACES="$(WORKSPACES)"

inventory:
	@bash bin/nix-xd-inventory "$(MACHINE)"

ghxd-auth:
	@NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' bash bin/nix-xd-ghxd-auth

ghxd-token-check:
	@NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' bash bin/nix-xd-log "$(SCOPE)" ghxd-token-check bash bin/nix-xd-ghxd-token-check

age-setup:
	@$(MAKE) --no-print-directory bootstrap PROVIDER=podman MACHINE="$(MACHINE)" SCOPE="$(SCOPE)" WORKSPACES="$(WORKSPACES)" WORKSPACE_ACCESS=rw AGE_VOLUME="$(SCOPE)-age" AGE_ACCESS=rw

qualify-ghxd-auth:
	@NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' GITHUB_CLIENT_ID='$(GITHUB_CLIENT_ID)' \
	  bash bin/nix-xd-log "$(SCOPE)" qualify-ghxd-auth bash bin/nix-xd-qualify-ghxd-auth

qualify-ghxd:
	@$(MAKE) --no-print-directory qualify-ghxd-auth PROVIDER=podman MACHINE="$(MACHINE)" SCOPE="$(SCOPE)" GITHUB_CLIENT_ID="$(GITHUB_CLIENT_ID)"
	@echo 'Native SOPS and GitHub device qualification passed; full cache/closure qualification remains separate.'


qualify-smoke:
	@test "$(PROVIDER)" = podman || { echo 'qualify-smoke requires PROVIDER=podman' >&2; exit 2; }
	@NIX_XD_MACHINE='$(MACHINE)' NIX_XD_SCOPE='$(SCOPE)' bash bin/nix-xd-log "$(SCOPE)" qualify-smoke bash bin/nix-xd-qualify-smoke

workspace-check:
	@$(TASK_ENV) bash bin/nix-xd-log "$(SCOPE)" workspace-check bash bin/nix-xd-workspace-check

store-export store-import:
	@$(TASK_ENV) NIX_XD_STORE_PATH="$(STORE_PATH)" bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-store-copy "$@"

share-check:
	@$(TASK_ENV) NIX_XD_READER_SCOPE="$(READER_SCOPE)" NIX_XD_SMOKE_SOURCE="$(SMOKE_SOURCE)" NIX_XD_EXCHANGE_ROOT="$(EXCHANGE_ROOT)" bash bin/nix-xd-log "$(SCOPE)" share-check bash bin/nix-xd-share-check

ifeq ($(PROVIDER),podman)
ifeq ($(OS),Darwin)
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
image-build:
	@$(MAKE) --no-print-directory bootstrap PROVIDER=podman MACHINE="$(MACHINE)" SCOPE="$(SCOPE)" WORKSPACES="$(WORKSPACES)"
else ifeq ($(PROVIDER),container)
ifeq ($(OS),Darwin)
APPLE = NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" bash bin/nix-xd-container
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
	@bash -n arm/bootstrap-macos.sh arm/bootstrap-podman.sh arm/bootstrap-container.sh bin/nix-xd-container bin/nix-xd-task bin/nix-xd-sync bin/nix-xd-log bin/nix-xd-plan bin/nix-xd-smoke bin/nix-xd-workspace-check bin/nix-xd-qualify-smoke bin/nix-xd-qualify-ghxd bin/nix-xd-qualify-ghxd-auth bin/nix-xd-ghxd-auth bin/nix-xd-ghxd-token-check bin/nix-xd-age-setup bin/nix-xd-store-copy
	@$(MAKE) --no-print-directory -n PROVIDER=podman OS=Linux plan sync stage build show qualify-process >/dev/null
	@$(MAKE) --no-print-directory -n PROVIDER=container OS=Darwin plan bootstrap stage build show qualify-composition >/dev/null
	@echo 'Static command checks passed; no ARM runtime executed.'
