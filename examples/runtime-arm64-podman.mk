# Local runtime selection; consumed by Make before its defaults.
ARCH = arm64
PROVIDER = podman
MACHINE = coreos-arm64
SCOPE = nix-xd-arm
WORKSPACES = $(abspath $(CURDIR)/..)
CHECKOUT = $(notdir $(CURDIR))
WORKLOAD_FLAKE = /workspaces/$(CHECKOUT)
export NIX_XD_LOG_DIR = $(HOME)/.local/nix.xd/logs
ARTIFACT_ROOT = $(HOME)/.local/nix.xd/artifacts
LIFECYCLE = reusable
