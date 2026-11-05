# Generic rootless Nix-Alpine runner; application composition belongs to callers (e.g. Agni).
SHELL := /bin/sh
.DEFAULT_GOAL := help

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
	  'make bootstrap               Initialize macOS Podman Machine + ARM Quadlet' \
	  'make plan                    Display host/runtime configuration' \
	  'make machine-start|machine-stop' \
	  'make build                   Rebuild ARM64 image' \
	  'make start|stop|restart      Manage rootless Quadlet service' \
	  'make status|logs|shell       Inspect or enter the runner' \
	  'make exec CMD="..."          Execute a command inside Nix-Alpine' \
	  'make run CMD="..."           Alias for exec (non-interactive)' \
	  'make sync WORKSPACE=path     Copy an application checkout into runner' \
	  'make compose WORKSPACE=path COMPOSE_CMD="..."   Sync then execute application command' \
	  'make check                   Validate bootstrap and Makefile syntax'

bootstrap:
	@test "$(OS)" = Darwin || { echo "macOS bootstrap requires Darwin" >&2; exit 1; }
	@NIX_XD_MACHINE="$(MACHINE)" NIX_XD_SCOPE="$(SCOPE)" bash arm/bootstrap-macos.sh

plan:
	@printf 'OS: %s\nMachine: %s\nScope: %s\nImage: %s\nWorkspace: %s\n' \
	  '$(OS)' '$(MACHINE)' '$(SCOPE)' '$(IMAGE)' '$(WORKSPACE)'

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

check:
	@bash -n arm/bootstrap-macos.sh
	@$(MAKE) --no-print-directory -n plan build status shell >/dev/null
	@echo 'Static checks passed (no macOS VM execution)'
