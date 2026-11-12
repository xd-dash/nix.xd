# Historical VM1 controller compatibility only. No new composition work here.
# Enable explicitly after selecting an existing legacy generation.
FATLINE_PROBE_REV ?=
export NIX_XD_FATLINE_PROBE_REV = $(FATLINE_PROBE_REV)

.PHONY: agni-coreos-plan-check
agni-coreos-plan-check:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/agni_coreos_plan.py

# Agni owns Fatline service/security templates; this is the host adapter.
FATLINE_PROFILE ?= vm1
FATLINE_SCOPE ?= fatline-arm-$(FATLINE_PROFILE)
export NIX_XD_FATLINE_PROFILE = $(FATLINE_PROFILE)
export NIX_XD_FATLINE_SCOPE = $(FATLINE_SCOPE)
.PHONY: fatline-prepare fatline-start fatline-status fatline-qualify fatline-stop fatline-host-link fatline-host-link-phases
fatline-prepare fatline-start fatline-status fatline-qualify fatline-stop fatline-adapter-refresh:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_host_link.py $(patsubst fatline-%,%,$@)
fatline-host-link:
	@bash bin/nix-xd-log "$(SCOPE)" fatline-host-link $(MAKE) --no-print-directory fatline-host-link-phases
fatline-host-link-phases:
	@$(MAKE) --no-print-directory -j1 -S fatline-prepare fatline-start fatline-adapter-refresh fatline-qualify fatline-status


.PHONY: fatline-logmash fatline-logmash-phases fatline-logmash-qualify
fatline-logmash:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory fatline-logmash-phases
fatline-logmash-phases:
	@$(MAKE) --no-print-directory -j1 -S wisp-go-build wisp-go-check fatline-prepare fatline-start fatline-adapter-refresh fatline-logmash-qualify
fatline-logmash-qualify:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_logmash.py

.PHONY: fatline-adapter-refresh


.PHONY: fatline-services-prepare fatline-services-activate fatline-services-qualify fatline-services-status fatline-services-stop fatline-services-local fatline-services-phases
fatline-services-prepare fatline-services-refresh fatline-services-probe-refresh fatline-services-configure-logma fatline-services-activate fatline-services-qualify fatline-services-status fatline-services-stop:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_services.py $(patsubst fatline-services-%,%,$@)
fatline-services-local:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory fatline-services-phases
fatline-services-phases:
	@$(MAKE) --no-print-directory -j1 -S fatline-services-prepare fatline-services-activate fatline-services-qualify fatline-logmash-qualify fatline-services-status

.PHONY: fatline-services-refresh

.PHONY: fatline-services-probe-refresh


.PHONY: fatline-resource-local fatline-resource-phases
fatline-resource-local:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory fatline-resource-phases
fatline-resource-phases:
	@$(MAKE) --no-print-directory -j1 -S fatline-services-configure-logma project-host-run

.PHONY: fatline-services-configure-logma

.PHONY: fatline-vm-start fatline-vm-local fatline-vm-phases wisp-go-linux fatline-cross-qualify
fatline-vm-start:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_vm.py
fatline-vm-local:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory fatline-vm-phases
fatline-vm-phases:
	@$(MAKE) --no-print-directory agni-coreos-plan-check
	@$(MAKE) --no-print-directory -j1 -S fatline-vm-start fatline-prepare fatline-start fatline-adapter-refresh fatline-services-prepare fatline-services-activate fatline-services-qualify fatline-services-configure-logma project-host-run fatline-services-status
wisp-go-linux:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" bash bin/nix-xd-wisp-go linux
fatline-cross-qualify:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_cross.py


.PHONY: fatline-restart-upgrade fatline-restart-recover fatline-restart-diagnose fatline-restart-prepare fatline-restart-qualify fatline-restart-local fatline-restart-phases
fatline-restart-prepare fatline-restart-qualify fatline-restart-diagnose fatline-restart-upgrade fatline-restart-recover:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_recovery.py $(patsubst fatline-restart-%,%,$@)
fatline-restart-local:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" $(MAKE) --no-print-directory fatline-restart-phases
fatline-restart-phases:
	@$(MAKE) --no-print-directory -j1 -S fatline-restart-prepare fatline-restart-qualify fatline-services-qualify project-host-run fatline-services-status

.PHONY: fatline-reboot-plan fatline-reboot-local fatline-reboot-resume
fatline-reboot-plan:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_reboot.py plan
fatline-reboot-local:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_reboot.py run
fatline-reboot-resume:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_reboot.py resume

.PHONY: fatline-rebootstrap-plan fatline-rebootstrap-local
fatline-rebootstrap-plan:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_rebootstrap.py plan
fatline-rebootstrap-local:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_rebootstrap.py run

# Sandbox lifecycle: resolve one generation, qualify, then atomically select it.
SANDBOX_REBOOT ?= 0
.PHONY: fatline-sandbox-plan fatline-sandbox-local fatline-sandbox-status
fatline-sandbox-plan:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_rebootstrap.py plan
fatline-sandbox-local:
	@NIX_XD_SANDBOX_REBOOT='$(SANDBOX_REBOOT)' WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_rebootstrap.py run
fatline-sandbox-status:
	@bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_rebootstrap.py status

.PHONY: fatline-profile-local
fatline-profile-local:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_profile.py

.PHONY: fatline-profile-reliability fatline-profile-recover
fatline-profile-reliability:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_profile.py qualify-reliability
fatline-profile-recover:
	@WISP_SMOKE_REV='$(WISP_SMOKE_REV)' bash bin/nix-xd-log "$(SCOPE)" "$@" "$(PYTHON)" lib/fatline_profile.py recover

