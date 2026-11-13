{ system, worlds ? 1 }:
assert builtins.isInt worlds && worlds >= 0 && worlds <= 7;
let
  scope = "shoal";
  worldNames = builtins.genList (index: "world" + toString (index + 1)) worlds;
  guests = [ "farcaster" ] ++ worldNames;
  mkGuest = name: {
    name = name;
    value = {
      kind = "coreos";
      transport = "9p";
      container = "coreos-shoal-" + name;
      sshPort = 2322 + (if name == "farcaster" then 0 else builtins.fromJSON (builtins.substring 5 1 name));
    };
  };
  guestDomain = name: {
    name = name + "-local";
    value = {
      owner = { placement = name; scopeStore = false; };
      readers = [ name ];
      provisioning = "deferred";
    };
  };
  guestWorkloads = name: [
    {
      name = name + "-a";
      value = { placement = name; domain = "common"; access = "read-only"; };
    }
    {
      name = name + "-b";
      value = { placement = name; domain = "common"; access = "read-only"; };
    }
  ];
in {
  version = 1;
  name = scope;
  inherit system;
  topology = {
    name = scope;
    region = "regional";
    addressFamilies = [ "ipv4" "ipv6" ];
    farcaster = "farcaster";
    members = [ "farcaster" ] ++ builtins.genList (index: "world" + toString (index + 1)) 7;
    active = guests;
    maxWorlds = 7;
    egress = {
      gateway = "farcaster";
      proxy = "squid";
      protocol = "http-connect";
      directWorldEgress = "deny";
      qualified = false;
    };
    service = {
      owner = "agni";
      farcasterRoles = [ "redis" "nginx" "logma" "skymill" "squid" ];
      client = "logmash";
    };
    # Store transport and network egress are independent qualifications.
    storage = {
      owner = "host";
      common = "read-only-9p";
      guestContainers = "read-only-bind-from-9p";
      guestLocal = "guest-owned";
      crossVmWritableStore = false;
    };
  };
  placements = { host = { kind = "host"; transport = "bind"; }; }
    // builtins.listToAttrs (map mkGuest guests);
  domains = {
    common = {
      owner = { placement = "host"; scopeStore = true; };
      readers = [ "host" ] ++ guests;
      provisioning = "existing-host-store";
    };
  } // builtins.listToAttrs (map guestDomain guests);
  workloads = {
    host-a = { placement = "host"; domain = "common"; access = "read-only"; };
    host-b = { placement = "host"; domain = "common"; access = "read-only"; };
  } // builtins.listToAttrs (builtins.concatMap guestWorkloads guests);
}
