# Historical Shoal-specific qualification. Agni owns this policy in the canonical architecture.
# Retain only for previously qualified evidence and old callers; do not extend.
# Shoal is a regional Farcaster/World contract; storage checks reuse running guests.
# Network qualification remains blocked until routed dual-stack Shoal networking exists.
SHOAL_STAGE ?= farcaster
SHOAL_GATE ?= all
SHOAL_FARCASTER_PORT ?= 2222
SHOAL_WORLD1_PORT ?= 2223
SHOAL_SSH_KEY ?= $(HOME)/.ssh/starwisp-test
SHOAL_SSH_USER ?= wisp
SHOAL_STATE_ROOT ?= $(GUEST_STATE_ROOT)
.PHONY: shoal-qualify
shoal-qualify:
	@$(MAKE) --no-print-directory stage CHECKOUT="$(notdir $(CURDIR))"
	@bash bin/nix-xd-log "$(SCOPE)" shoal-qualify "$(PYTHON)" lib/shoal_runtime.py \
	  --stage "$(SHOAL_STAGE)" --gate "$(SHOAL_GATE)" \
	  --provider "$(PROVIDER)" --machine "$(MACHINE)" --owner "$(SCOPE)" \
	  --flake "/workspaces/$(notdir $(CURDIR))" \
	  --ssh-key "$(SHOAL_SSH_KEY)" --ssh-user "$(SHOAL_SSH_USER)" \
	  --state-root "$(SHOAL_STATE_ROOT)" \
	  --farcaster-port "$(SHOAL_FARCASTER_PORT)" \
	  --world1-port "$(SHOAL_WORLD1_PORT)"

