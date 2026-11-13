.PHONY: bootstrap-amd64
bootstrap-amd64:
	@NIX_XD_PROVIDER='$(PROVIDER)' NIX_XD_SCOPE='$(SCOPE)' NIX_XD_WORKSPACES='$(WORKSPACES)' NIX_XD_IMAGE='$(IMAGE)' bash bin/nix-xd-log "$(SCOPE)" bootstrap bash bin/nix-xd-bootstrap-amd64
