# Make controls; Nix-Alpine executes project flakes

`project-run` is a generic host launcher. Make selects the provider, architecture,
existing builder, project flake, app and structured arguments. The logger stays on
the host. The launcher then invokes Nix inside Nix-Alpine; its packaged runtime
launches the selected project app there. Python is a flake dependency, not a new
host bootstrap requirement.

The first extracted runtime package supplies process execution/timeouts, atomic
JSON writes and caller-scoped locking. It has no Fatline/Grml service rules or
store selection policy. The current ARM runtime sources live in nix.xd and export
`runtimePrimitives`, `runtimePython` and `project-launch`. Agni consumes the
package source at an exact revision. No change to the separately maintained
x86 Nix-Alpine source repository is claimed.

The initial Agni app is `local/fatline#startup`, with `check` and public-spec
`render` commands. Its checks exercise the existing renderer and bootstrap-hook
success/failure cleanup tests. They do not deploy Fatline, restart containers,
modify credentials, or claim a real guest/bootstrap-crash qualification.

Using the existing `fatline` Make launcher function:

```bash
fatline stage &&
fatline project-run \
  PROJECT_FLAKE='github:dash-xd/agni/670f933a20ceba0b410c6c19b69f72ede209384a?dir=local/fatline' \
  PROJECT_APP=startup PROJECT_ARGS_JSON='["check"]'
```

Success prints `PROJECT_EXECUTOR=linux` and `AGNI_STARTUP_CHECK=passed executor=linux`.
Arguments are decoded as a JSON array inside the packaged Linux launcher and
passed directly to Nix; they are not interpreted as shell code. Existing provider
architecture validation and `NIX_XD_LOG_DIR` apply. The generic launcher introduces
no GitHub login flow; existing runtime authentication remains available through
its established configuration. No tokens enter the source or runtime dependency
input. All new source dependencies use exact revisions.

## Remaining extraction

The legacy host Fatline controllers and their application gates still exist.
This first check deliberately does not wrap those controllers in a Linux flake
and call that a completed extraction. Their checkout-relative state, Mac-native
binaries and host-loopback assumptions must not become generic runtime APIs.
Agni's next controller should resolve its deployment and run its local
orchestration in Nix-Alpine, with declared Smoke/Wisp capabilities where a host
operation is actually needed. It can create fresh sandbox state rather than
introduce migration machinery for the old evolving deployment.

Keep the old controllers only as a reference and existing qualification path
until the new application entrypoint covers those behaviours. Move each
application qualification intact with its owning Agni operation; do not waive
ACL, dependency-failure, recovery or boot checks during that replacement.

Store/chroot adapters are unchanged. Project invocations do not implicitly merge
stores, remount peer volumes, or change the builder's writable-store selection.
