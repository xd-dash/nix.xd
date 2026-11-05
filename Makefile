# Generic rootless Nix-Alpine runner; application composition belongs to callers (e.g. Agni).
SHELL := /bin/sh
.DEFAULT_GOAL := help

PROVIDER ?= podman
MACHINE ?= podman-machine-default
SCOPE ?= nix-xd-arm
IMAGE ?= localhost/nix-xd:arm64
CMD ?= nix --version
WORKSPACE ?=
WORKDIR ?= /home/nixuser/workspace
COMPOSE_CMD ?= pwd
OS := $(shell uname -s)

.PHONY: help bootstrap plan machine-start machine-stop build start stop restart status logs shell exec run sync compose check

help:
	@printf '%s\n' \
	  'make bootstrap PROVIDER=podman|container    Initialize ARM runtime (default podman)' \
	  'make plan                    Display host/runtime configuration' \
	  'make machine-start|machine-stop' \
	  'make build                   Rebuild ARM64 image' \
	  'make start|stop|restart      Manage rootless Quadlet service' \
	  'make status|logs|shell       Inspect or enter the runner' \
	  'make exec CMD="..."          Execute a command inside Nix-Alpine' \
	  'make run CMD="..."           Alias for exec (non-interactive)' \
	  'make sync WORKSPACE=path     Copy an application checkout into runner' \
	  'make compose WORKSPACE=path COMPOSE_CMD="..."   Sync then execute application command' \
	  'make check                   Validate both provider scripts and Make targets'

bootstrap:
	@test "$(OS)" = Darwin || { echo "macOS bootstrap requires Darwin" >&2; exit 1; }
	@NIX_XD_PROVIDER="$(PROVIDER)" NIX_XD_MACHINE="$(MACHINE)" NIX_XD_SCOPE="$(SCOPE)" NIX_XD_IMAGE="$(IMAGE)" bash arm/bootstrap-macos.sh

plan:
	@printf 'OS: %s\nProvider: %s\nMachine: %s\nScope: %s\nImage: %s\nWorkspace: %s\n' \
	  '$(OS)' '$(PROVIDER)' '$(MACHINE)' '$(SCOPE)' '$(IMAGE)' '$(WORKSPACE)'

ifeq ($(PROVIDER),container)
ifeq ($(OS),Darwin)
CONTAINER_RUN = NIX_XD_SCOPE='$(SCOPE)' NIX_XD_IMAGE='$(IMAGE)' NIX_XD_WORKSPACE='$(WORKSPACE)' NIX_XD_WORKDIR='$(WORKDIR)' bash bin/nix-xd-container
machine-start machine-stop build start stop restart status logs shell:
	@$(CONTAINER_RUN) $@

exec run:
	@NIX_XD_CMD='$(CMD)' $(CONTAINER_RUN) $@

sync:
	@$(CONTAINER_RUN) sync

compose:
	@NIX_XD_COMPOSE_CMD='$(COMPOSE_CMD)' $(CONTAINER_RUN) compose
else
$(error PROVIDER=container requires Apple Silicon macOS)
endif
else ifeq ($(PROVIDER),podman)
ifeq ($(OS),Darwin)
machine-start:
	@state="$$(podman machine inspect "$(MACHINE)" --format '{{.State}}')"; \
	  if [ "$$state" != running ]; then podman machine start "$(MACHINE)"; fi

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
	@echo 'Podman Machine is not required on native Linux.'

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

build: machine-start
	@podman build --platform linux/arm64 -t "$(IMAGE)" ./arm

shell:
	@podman exec -it "$(SCOPE)" bash -l

exec run:
	@podman exec "$(SCOPE)" bash -lc '$(CMD)'

# No host bind mounts: podman cp creates a snapshot inside the container.
# Application command and dependencies remain owned by the application repository.
sync:
	@test -n "$(WORKSPACE)" && test -d "$(WORKSPACE)" || { \
	  echo "Set WORKSPACE to a local application directory" >&2; exit 2; }
	@podman exec "$(SCOPE)" mkdir -p "$(WORKDIR)"
	@podman cp "$(WORKSPACE)/." "$(SCOPE):$(WORKDIR)/"

compose: sync
	@podman exec -w "$(WORKDIR)" "$(SCOPE)" bash -lc '$(COMPOSE_CMD)'

else
$(error Unsupported PROVIDER='$(PROVIDER)': use podman or container)
endif

check:
	@bash -n arm/bootstrap-macos.sh arm/bootstrap-podman.sh arm/bootstrap-container.sh bin/nix-xd-container
	@$(MAKE) --no-print-directory -n PROVIDER=podman plan build status shell >/dev/null
	@$(MAKE) --no-print-directory -n PROVIDER=container OS=Darwin plan build status shell >/dev/null
	@echo 'Static checks passed (no macOS VM execution)'
