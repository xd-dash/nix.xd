# Transitional macOS-hosted application dispatch; not canonical after bootstrap.
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
	@$(TASK_ENV) NIX_XD_IMAGE='$(IMAGE)' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-project-host-run

