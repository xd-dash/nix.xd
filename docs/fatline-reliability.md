# Fatline reliability contract

Nix-Alpine bootstrap is being developed iteratively and is outside these gates.
This does not waive application, guest boot, or composition qualification.

## Review of the profile consolidation

No existing test suite was deleted. However, the initial consolidated profile
set Redis to `Restart=no`, prevented legacy restart commands from mutating the
new profile, and provided no equivalent reliability gate. The bootstrap failure
gate was also deferred. That reduced application-level coverage and recovery.
The correction keeps one Agni-owned profile and restores reliability there,
without reintroducing configuration/recovery overlays or Nix-Alpine tests.

* Every service has `Restart=on-failure`, a five-second delay, and a three-start
  limit per 120 seconds. Persistent configuration faults can require managed
  recovery after fixing their inputs; there is no automatic reboot or rollback.
* Redis upholds its application group. Consumers bind to Redis and start after
  its bootstrap hook succeeds. Logma also binds to nginx. The profile checks that
  the running user manager recognizes the Upholds relationships.
* Bootstrap prepares a private runtime ACL, installs Functions, revokes the
  privileged identity, then records the Redis invocation. Failure revokes the
  file and leaves no ready marker; systemd stops Redis and blocks dependents.
* All services still require the read-only store barrier, separate scoped mounts
  and credentials, rootless execution, and the existing private ingress contract.
* Roots stay retained across failures; logical locks serialize controller work.
  Evidence is scoped to the installed source and current guest boot. A changed
  boot requires explicit reconciliation, never an assumed successful recovery.

## Focused local gate

`fatline-profile-reliability` uses a temporary user-runtime systemd override to
fail Redis's bootstrap hook. It checks that dependents are unavailable and the
runtime bootstrap identity is disabled. It removes the override, starts Redis,
and checks successful bootstrap and live denial of bootstrap credentials.
It then kills Redis and waits for a new ready invocation and new containers
without calling controller start/recover. Service checks and host subscriber
checks run afterward; the CoreOS boot and VM2 must remain unchanged.

The override never edits source, passwords, the canonical ACL, or Ignition. Normal
exit removes it. If the controller/SSH session is interrupted, the explicit
`fatline-profile-recover` removes that exact override and starts the declared
group. Recovery does not fabricate a passed reliability receipt. Logs and failed
receipts remain available. Redis data is currently ephemeral and is lost.

`fatline-reboot-local` remains the separate gate for autonomous startup after
CoreOS reboot, store-before-service ordering, bootstrap revocation, boot-record
reconciliation, host delivery, and an unchanged VM2. A service gate does not
imply a reboot result. No routine application edit requires a rebootstrap.

## Qualification boundaries and GCP

| Layer | Required contract | Current limit |
| --- | --- | --- |
| Application group | Dependency failure blocks ingress/apps; bounded restart; Functions/ACL reconciliation; real delivery after recovery | New profile needs the local reliability and reboot receipts; production publisher reconciliation remains separate |
| CoreOS guest | Boot with available read-only closures, user-manager startup and runtime credentials; identify new boot | Earlier graph passed a reboot; the updated graph must pass separately |
| QEMU runner | Explicit start/stop, retained disks/closures, unambiguous guest identity and resource allocation | Runner crash and parent reboot supervision are not qualified; no automatic parent recovery is claimed |
| GCP parent VM | Provision virtualization-capable compute, start runners and provide declared storage/networking | No GCE adapter or nested-virtualization qualification exists yet |
| Parent/spot replacement | Reattach durable state and deliver closures/credentials, reconstruct guests, reconcile identities | Requires storage and placement decisions, then a replacement gate; an in-guest restart cannot prove this |

Agni owns machine and service declarations. nix.xd selects architecture,
placement, closures, roots and qualification adapters. Smoke/Wisp supplies
execution, credential and transport primitives. Keep this boundary when adding a
GCP parent with multiple QEMU guests: parent supervision starts runners; each
guest's systemd starts its Fatline. Do not put GCP APIs or parent repair logic
inside application Quadlets. Hardware, machine type and nested acceleration must
be selected and qualified before promising the nested topology.

Local 9P and host-brokered SSH remain explicit adapters, not cloud networking or
storage guarantees. Parent loss can affect both guest VMs, so two guests on one
parent are not separate failure domains. Spot replacement must also distinguish
reconstructible build closures from durable Redis/Skymill/application state.

Still required before full Fatline qualification: running Logma publisher
reconciliation, adversarial tenants within one Redis, durable Redis restart and
Skymill pending recovery, backup/restore, then GCE ingress/storage and parent
replacement qualification. Database slots and subnets alone are not tenant
security boundaries. Preserve ACL key/channel/command restrictions and the
filesystem mount boundaries in every adapter.
