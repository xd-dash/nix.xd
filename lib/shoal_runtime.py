#!/usr/bin/env python3
"""Shoal runtime storage qualification using existing CoreOS/9P guests."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

STORE = re.compile(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+")
GUEST_PROBE = r"""set -Eeuo pipefail
mountpoint=/var/mnt/nixstore
test "$(findmnt -rn -o FSTYPE --mountpoint "$mountpoint")" = 9p
options="$(findmnt -rn -o OPTIONS --mountpoint "$mountpoint")"
[[ ",$options," == *,ro,* ]]
store="$mountpoint/${SHOAL_PROBE_ROOTFS#/nix/store/}"
test -L "$store/bin/sh"
busybox="$(readlink "$store/bin/sh")"
[[ "$busybox" == /nix/store/*/bin/busybox ]]
actual="$(sha256sum "$mountpoint/${busybox#/nix/store/}" | cut -d ' ' -f 1)"
[[ "$actual" == "$SHOAL_EXPECTED_BUSYBOX_SHA256" ]]
test "$(podman info --format '{{.Host.Security.Rootless}}')" = true
boot="$(cat /proc/sys/kernel/random/boot_id)"
for n in a b; do
  scratch="$(mktemp -d)"
  chmod 700 "$scratch"
  cleanup() { podman unshare rm -rf -- "$scratch"; }
  trap cleanup EXIT
  mkdir -p "$scratch/bin" "$scratch/nix/store" "$scratch/tmp"
  ln -s "$SHOAL_PROBE_ROOTFS/bin/sh" "$scratch/bin/sh"
  podman run --rm --network none --pull=never \
    --userns keep-id:uid=1000,gid=1000 --user 1000:1000 \
    --read-only --read-only-tmpfs=false --security-opt label=disable \
    --cap-drop all --security-opt no-new-privileges \
    --mount "type=bind,src=$mountpoint,dst=/nix/store,ro" \
    --rootfs "$scratch" /bin/sh -ec \
      'test -x "$1/bin/sh"; test "$("$2" sha256sum "$2" | "$2" cut -d " " -f 1)" = "$3"; if echo write > /nix/store/shoal-write-probe 2>/dev/null; then exit 1; fi' \
      sh "$SHOAL_PROBE_ROOTFS" "$busybox" "$SHOAL_EXPECTED_BUSYBOX_SHA256"
  cleanup
  trap - EXIT
  echo "SHOAL_GUEST_READER=passed container=$n store=9p-ro"
done
test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot"
echo "SHOAL_GUEST_STORAGE=passed boot=unchanged container_readers=2"
"""


def run(argv, input_text=None, timeout=120):
    completed = subprocess.run(argv, input=input_text, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout, check=False)
    if completed.returncode:
        raise ValueError("Command failed (" + str(completed.returncode) + "): " +
                         argv[0] + ": " + completed.stderr[-1200:])
    return completed.stdout.strip()


def names(stage):
    if stage == "farcaster":
        return ("farcaster",)
    if stage == "world1":
        return ("farcaster", "world1")
    raise ValueError("Shoal runtime only supports farcaster or world1 stages")


def endpoints(args):
    for name in names(args.stage):
        port = getattr(args, name + "_port")
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid guest SSH port")
        known = Path(args.state_root) / ("starwisp" if name == "farcaster" else "shoal-world1") / "known_hosts"
        if not known.is_file():
            raise ValueError("Existing SSH host identity unavailable: " + str(known))
        yield name, port, known


def ssh(args, port, known, script, rootfs, expected_sha256):
    return run(["ssh", "-T", "-i", args.ssh_key, "-p", str(port),
                "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
                "-o", "UserKnownHostsFile=" + str(known),
                args.ssh_user + "@127.0.0.1",
                "env", "SHOAL_PROBE_ROOTFS=" + rootfs,
                "SHOAL_EXPECTED_BUSYBOX_SHA256=" + expected_sha256, "bash", "-se"], script)


def storage(args):
    if not Path(args.ssh_key).is_file():
        raise ValueError("Missing SSH key")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", args.owner):
        raise ValueError("Invalid Nix-Alpine owner")
    if args.provider == "podman":
        podman = ["podman", "--connection", args.machine]
        volume_format = '{{range .Mounts}}{{if eq .Destination "/nix"}}{{.Name}}{{end}}{{end}}'
        owner_volume = run(podman + ["inspect", args.owner, "--format", volume_format])
        if owner_volume != args.owner + "-store":
            raise ValueError("Nix store owner volume differs from expected scope")
        executor = podman + ["exec", args.owner]
    else:
        executor = ["container", "exec", args.owner]
        owner_volume = args.owner + "-store"
        inspect = run(["container", "inspect", args.owner])
        if not re.search(r'"name"\s*:\s*"' + re.escape(owner_volume) + r'"', inspect):
            raise ValueError("Apple container does not mount expected owner volume")
        run(executor + ["test", "-f", "/nix/.nix-xd-direct-volume-v2"])
    rootfs = run(executor + ["nix", "build", "--no-link",
                  "--no-write-lock-file", "--print-out-paths",
                  args.flake + "#storeProbeRootfs^out"], timeout=600)
    if not STORE.fullmatch(rootfs):
        raise ValueError("Unexpected store probe rootfs")
    run(executor + ["test", "-x", rootfs + "/bin/sh"])
    busybox = run(executor + ["readlink", rootfs + "/bin/sh"])
    if not re.fullmatch(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+/bin/busybox", busybox):
        raise ValueError("Store probe executable is not a pinned BusyBox")
    expected_sha256 = run(executor + ["sha256sum", busybox]).split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Invalid probe checksum")
    print("SHOAL_STORE_OWNER=passed volume=" + owner_volume + " read_only_guests=true", flush=True)
    for name, port, known in endpoints(args):
        result = ssh(args, port, known, GUEST_PROBE, rootfs, expected_sha256)
        if result.count("SHOAL_GUEST_READER=passed") != 2 or "SHOAL_GUEST_STORAGE=passed" not in result:
            raise ValueError("Incomplete guest 9P/container evidence: " + name)
        print("SHOAL_STORAGE_GUEST=passed name=" + name + " 9p=ro readers=2", flush=True)
    print("SHOAL_STORAGE=passed stage=" + args.stage + " 9p=ro guest_local=unchanged activation=blocked", flush=True)


def network(args):
    # The current QEMU runner uses per-VM user networking, without a
    # shared guest subnet or an enforced deny-direct egress firewall.
    # Do not claim Squid/IPv6 qualification through host-forwarded SSH.
    raise ValueError(
        "SHOAL_NETWORK=blocked reason=shared-dual-stack-subnet-and-egress-deny-adapter-not-implemented"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("farcaster", "world1"), default="farcaster")
    parser.add_argument("--gate", choices=("storage", "network", "all"), default="all")
    parser.add_argument("--owner", default="nix-xd-arm")
    parser.add_argument("--machine", default="coreos-arm64")
    parser.add_argument("--provider", choices=("podman", "container"), default="podman")
    parser.add_argument("--flake", default="/workspaces/nix.xd20261112")
    parser.add_argument("--ssh-key", default=str(Path.home() / ".ssh/starwisp-test"))
    parser.add_argument("--ssh-user", default="wisp")
    parser.add_argument("--state-root", default=str(Path.home() / ".local/state/nix-xd/coreos"))
    parser.add_argument("--farcaster-port", type=int, default=2222)
    parser.add_argument("--world1-port", type=int, default=2223)
    args = parser.parse_args()
    if args.gate in ("storage", "all"):
        storage(args)
    if args.gate in ("network", "all"):
        network(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("SHOAL_QUALIFY=blocked " + str(exc), file=sys.stderr)
        sys.exit(1)
