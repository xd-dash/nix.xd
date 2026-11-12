.PHONY: bootstrap-arm64
bootstrap-arm64:
	@test "$(OS)" = Darwin || { echo "ARM64 bootstrap adapter currently requires macOS" >&2; exit 2; }
	@NIX_XD_ARCH='$(ARCH)' NIX_XD_PROVIDER='$(PROVIDER)' $(MACHINE_ENV) NIX_XD_SCOPE='$(SCOPE)' NIX_XD_IMAGE='$(IMAGE)' NIX_XD_INITIAL_PROFILE='$(INITIAL_PROFILE)' NIX_XD_INITIAL_CHROOT_STORES='$(INITIAL_CHROOT_STORES)' NIX_XD_GRANTS_FILE='$(GRANTS_FILE)' bash bin/nix-xd-log "$(SCOPE)" bootstrap bash arm/bootstrap-macos.sh
