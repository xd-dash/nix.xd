# Shoal: regional dual-stack qualification

Shoal is one **regional** subnet and eight logical members, not an
independent cluster for each test: **Farcaster + seven Worlds**. The name
describes the final topology; qualification grows the same topology
without requiring eight guests from the beginning.

| Stage | Nix-Alpine store owner | CoreOS guests | Nix-Alpine readers |
| --- | --- | --- | --- |
| Host + Farcaster | 1 on host | Farcaster | Two on host, two on Farcaster |
| Host + two guests | 1 on host | Farcaster, World 1 | Two on each placement |
| Full Shoal | Owner selected by deployment | Farcaster, Worlds 1–7 | Two per placement as a capacity/ownership contract |

The two-reader fixtures are for isolation and store sharing.
They are **not** mandatory network proxies or a prescription to run
application workloads in every container. Future scale tests can reuse
the same declarations at the requested workload count.

## Storage invariants

* Nix-Alpine on the host owns and writes the **common** Nix store.
* QEMU transports common closures into CoreOS via **9P, read-only**.
* Containers inside each CoreOS guest bind that mounted store
  **read-only**. They must not acquire host store-write authority.
* Guest-local writable state/store stays in the owning guest.
  Farcaster's guest-local store must not become a writable shared store
  for World 1 (or vice versa).
* Preserve the existing generation-root and read-only
  mount validation, UID/mount identity, teardown/recreation and
  unchanged-neighbor checks before accepting a new topology.
* Inspect Nix roots on the owner; seeing an executable in a CoreOS
  9P mount is not proof of GC retention.
* A GCE adapter must separately qualify whichever backing store and
  transport replaces local 9P. Local QEMU evidence cannot be treated
  as proof of cloud sharing.

The existing `shared-store-matrix` stays intact as its previously
qualified local storage composition. Shoal is an **additive** logical
contract; do not rename or reset existing guest disks/stores to use it.

## Network qualification (not yet passed)

Farcaster will host Agni-managed Redis, Nginx, Logma, Skymill and Squid.
Worlds run Smoke Logmash clients and use Farcaster's Squid proxy for
HTTP/HTTPS egress over the declared IPv4/IPv6 subnet.

Qualify with real traffic and bounded checks, **separately** for each
address family:

1. Farcaster proxy reachable from the selected World; direct
   internet egress denied by actual routing/firewall policy.
2. HTTP and HTTPS CONNECT transit via Squid; deny unsupported
   destinations/ports, and prove no proxy bypass.
3. Logmash connects over the declared private Nginx/Redis path,
   delivers/acknowledges a scoped event; unauthorized identity and
   cross-World scope are denied.
4. Restart/recreate one guest and its containers; other members keep
   their boot, store roots, mount modes, and stream state as appropriate.
5. In the two-guest phase, inspect both 9P mounts and both sets of
   container mounts before claiming shared filesystem qualification.

Squid is an HTTP proxy, not a transparent gateway for arbitrary
protocols. IPv6 behavior is not implied by IPv4 success; test both.

## Implemented now

The declarations `compositions.shoal-host-farcaster`,
`compositions.shoal-host-farcaster-world1`, and
`compositions.shoal-eight` define the placement/store policy.
`tests/shoal-contract.py` statically rejects cross-guest writable
sharing and unqualified egress claims.

Existing `composition-*` execution is still restricted to
`shared-store-matrix`; Shoal is not an activated QEMU runner or
internet qualification yet. A future named Shoal execution adapter
should reuse the qualified local 9P/multi-container operations and
add explicit Squid/Logmash network checks rather than fork the
Nix-Alpine or QEMU lifecycle.

## Runtime storage gate (implemented; requires existing guests)

The named operation `shoal-qualify` uses existing CoreOS guests and the
existing Nix-Alpine store owner. It does not boot, reset, or install
VMs, and does not change Fatline's running deployment.

```sh
make shoal-qualify PROVIDER=podman SHOAL_GATE=storage SHOAL_STAGE=farcaster
make shoal-qualify PROVIDER=podman SHOAL_GATE=storage SHOAL_STAGE=world1
```

The host gate confirms a marked owner store volume, builds a small
existing Nix-store BusyBox probe, and checks a rootless 9P mount
inside each selected guest. Two ephemeral rootless Podman containers
per guest share that **same** read-only 9P-backed Nix closure; neither
can write to the common store. Boot IDs are compared before and
after. Existing credentials, Quadlets and application services are
not touched. The World 1 gate requires a separate, already
running CoreOS guest at the selected SSH port, with a pinned host
identity in `~/.local/state/nix-xd/coreos/shoal-world1/known_hosts`.

The guest SSH key, ports, and state root can be selected using
`SHOAL_SSH_KEY`, `SHOAL_FARCASTER_PORT`,
`SHOAL_WORLD1_PORT` and `SHOAL_STATE_ROOT`. The state root defaults to the
canonical generic guest transport directory `~/.local/state/nix-xd/coreos`;
it is not tied to the controller checkout. The selected Podman machine defaults
to Podman's current default connection. Farcaster port 2222 reuses the
Starwisp transport.

`SHOAL_GATE=all` deliberately returns a blocked result after the
storage gate because the existing QEMU runner uses **per-VM user
networking**, not a common routable dual-stack subnet. It is not
valid to count SSH forwarding as World-to-Farcaster network
qualification. Network qualification still requires a routed
Shoal adapter, Agni-managed Squid, IPv4/IPv6 HTTP(S) transit and
explicit direct-egress denial. The static plan is not a deployment.

Store visibility and the two-container check do **not** establish
GC-root retention, guest-local writable-store sharing, or
actual multi-VM networking. Those gates remain distinct.

The default and current recommended provider is `podman`. The Apple
`container` provider is legacy optional support and must not be selected
implicitly for Shoal. Shoal does not migrate stores between providers.
