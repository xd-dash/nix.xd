# Host source-checkout management; application execution stays in Nix-Alpine.
WORKSPACE_ROOT ?= $(HOME)/workspace
WORKSPACE_REPO ?= xd-dash/nix.xd
WORKSPACE_VERSION ?= $(shell date +%Y%m%d)
WORKSPACE_BASE ?=
export NIX_XD_WORKSPACE_ROOT = $(WORKSPACE_ROOT)
export NIX_XD_WORKSPACE_REPO = $(WORKSPACE_REPO)
export NIX_XD_WORKSPACE_VERSION = $(WORKSPACE_VERSION)
export NIX_XD_WORKSPACE_BASE = $(WORKSPACE_BASE)
.PHONY: workspace workspace-plan workspace-path workspace-check workspace-clean workspace-clean-plan
workspace:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workspace open
workspace-plan:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workspace plan
workspace-path:
	@bash bin/nix-xd-workspace path
workspace-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash tests/workspace-contract.sh
workspace-clean-plan:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workspace clean-plan
workspace-clean:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-workspace clean
