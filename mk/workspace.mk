# Host-side Git source lifecycle. Application execution remains in Nix-Alpine.
WORKSPACE_ROOT ?= $(HOME)/workspace
WORKSPACE_REPO ?= xd-dash/nix.xd
WORKSPACE_VERSION ?= $(shell date +%Y%m%d).0
WORKSPACE_BASE ?=
WORKSPACE_PR_BASE ?=
WORKSPACE_REMOVE_CONFIRM ?=
export NIX_XD_WORKSPACE_ROOT = $(WORKSPACE_ROOT)
export NIX_XD_WORKSPACE_REPO = $(WORKSPACE_REPO)
export NIX_XD_WORKSPACE_VERSION = $(WORKSPACE_VERSION)
export NIX_XD_WORKSPACE_BASE = $(WORKSPACE_BASE)
export NIX_XD_WORKSPACE_PR_BASE = $(WORKSPACE_PR_BASE)
export NIX_XD_WORKSPACE_REMOVE_CONFIRM = $(WORKSPACE_REMOVE_CONFIRM)

.PHONY: workspace workspace-init workspace-refresh workspace-list workspace-plan workspace-path workspace-pr workspace-remove-plan workspace-remove workspace-check workspace-clean workspace-clean-plan
workspace:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" python3 bin/nix-xd-workspace open
workspace-init workspace-refresh workspace-list workspace-plan workspace-pr workspace-remove-plan workspace-remove:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" python3 bin/nix-xd-workspace $(patsubst workspace-%,%,$@)
workspace-path:
	@python3 bin/nix-xd-workspace path
workspace-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" bash tests/workspace-contract.sh
workspace-clean workspace-clean-plan:
	@echo 'Automatic workspace deletion is retired. Use workspace-remove-plan/workspace-remove only after PR merge.' >&2
	@exit 2
