# Fatline sandbox generation contract

## Review of the November 10 ARM run

The replacement reached `FATLINE_REBOOT_RESULT=passed`. Its read-only store,
startup ordering, Functions installation/revocation, service ACLs, Skymill
roundtrip and authenticated host subscriber path passed. Activation then failed
because the controller required the previous guest's SSH endpoint to stay healthy.
That dependency was a migration policy imposed on a rebuildable sandbox.

The first software-emulated boot took 476 seconds. The mandatory reboot test
added another boot wait. Three simultaneous guests added resource contention;
the log does not establish whether the old guest exited from memory pressure,
updates, or an operator action. Do not infer that cause from connection refusal.
Untimestamped application phases prevent an exact end-to-end time breakdown.

## Ownership

| Component | Contract |
| --- | --- |
| Nix-Alpine | Authoritative writable store and builds; explicit retained roots |
| nix.xd | Resolve a generation; provision, qualify and select it through adapters |
| Agni | Ignition, CoreOS capabilities and complete systemd/Quadlet construction |
| Smoke/Wisp | Application execution, credentials, SSH transport and evidence |
| Fatline/Logma/Skymill | Application behavior, key/channel scopes and service contracts |
| Make | Thin, logged public interface |

The declarative bootstrap grants only the required reboot operation. Operators
never install policy through guest root or sudo. Bootstrap changes replace the VM.
ARM and x86 use the same post-bootstrap contracts; native x86 qualification is
still separate. Local 9P is one store-delivery adapter, not the GCE topology.

## Lifecycle

Resolve -> build -> provision -> qualify -> select.

A generation contains the exact bootstrap, transport, application, probe and
startup source selections; store outputs; physical guest placement; credential
file hashes; and qualification capabilities. Its manifest is written once.
Changing that manifest requires a new generation. Multiple constituent revisions
are explicit inputs, not permission to patch a running application in place.

Activation atomically writes one logical binding containing both the guest
placement and generation-local controller state. It never merges candidate
credentials/evidence back into the previous state directory. Control locks and
pending-operation checkpoints stay at the stable logical scope, so changing the
active generation cannot bypass serialization.

An already qualified replacement can activate without an SSH connection to the
old guest. Retirement uses its recorded Podman container ID; a different container
under the same name is rejected. Old disks, artifacts and roots stay retained.
The original shared artifact directory must remain in place while VM2 mounts it.

Future sandbox rebuilds stop the disposable old runner before booting a new one.
This deliberately permits downtime and reduces peak guest count to two. It is not
production blue/green migration. A failed rebuild retains its inputs and evidence;
it does not silently select an unqualified generation or garbage-collect roots.

Routine sandbox qualification is service readiness, ACLs, Skymill delivery/ack,
and host subscriber delivery. Reboot qualification is explicit. Records distinguish
those capabilities; service-only qualification never claims a reboot result.

## Operator interface

After staging, use `fatline-sandbox-local` to continue a pending operation or create
a fresh sandbox generation. A fresh build defaults to `SANDBOX_REBOOT=0`; use
`fatline-reboot-local` explicitly for the boot contract, or select
`SANDBOX_REBOOT=1` for a fresh generation that must pass it before selection.
The existing pending November 10 candidate already has a passed reboot receipt;
finishing its activation does not boot, rebuild or rerun qualification.

`fatline-sandbox-status` prints the selected generation and pending phase.
`generation.json` records resolved inputs at the generation-local controller root;
`.state/vm-bindings/<owner>/vm1.json` is the single activation record. Legacy
`fatline-rebootstrap-*` commands remain compatibility entrypoints, not a separate
migration architecture. Logs remain in `logs/`.

## Remaining work

* The historical activation/configuration/recovery steps now share one Agni
  startup profile. Qualify its service-failure and reboot contracts independently
  using the gates in [Fatline reliability](fatline-reliability.md).
* Qualify bootstrap failure injection, production publisher reconciliation, and two
  tenants in one Redis process. The resource dispatch still uses a finite fixture
  producer and is not production publisher orchestration.
* Decide persistence and backup/restore before claiming crash or spot replacement
  recovery. Redis remains ephemeral and full Fatline qualification remains false.
* Native HVF can avoid nested TCG, but its host-store delivery is not qualified.
  Switching accelerators must preserve the storage contract; it is not a flag-only
  optimization. Avoid repeated boot tests while developing application behavior.
* GCE needs a private-network/storage adapter and explicit firewall/identity policy.
  Local sharing and host-brokered SSH do not qualify GCE or tenant subnet isolation.
