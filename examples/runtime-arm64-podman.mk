# Local runtime selection; consumed by Make before its defaults.
ARCH = arm64
PROVIDER = podman
MACHINE = coreos-arm64
SCOPE = nix-xd-arm
WORKSPACES = $(abspath $(CURDIR)/..)
CHECKOUT = $(notdir $(CURDIR))
WORKLOAD_FLAKE = /workspaces/$(CHECKOUT)
export NIX_XD_LOG_DIR = $(HOME)/workspace/nix.xd/logs
