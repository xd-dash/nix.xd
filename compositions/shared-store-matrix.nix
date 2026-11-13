{ system }:
{
  version = 1;
  name = "shared-store-matrix";
  inherit system;
  domains = {
    common = {
      owner = { placement = "host"; scopeStore = true; };
      readers = [ "host" "vm1" "vm2" ];
      provisioning = "existing-host-store";
    };
    vm1-local = {
      owner = { placement = "vm1"; scopeStore = false; };
      readers = [ "vm1" ];
      provisioning = "deferred";
    };
    vm2-local = {
      owner = { placement = "vm2"; scopeStore = false; };
      readers = [ "vm2" ];
      provisioning = "deferred";
    };
    guests-shared = {
      owner = { placement = "host"; scopeStore = false; };
      readers = [ "vm1" "vm2" ];
      provisioning = "deferred";
    };
  };
  placements = {
    host = { kind = "host"; transport = "bind"; };
    vm1 = { kind = "coreos"; transport = "9p"; container = "coreos-starwisp"; sshPort = 2222; reusePrimary = true; };
    vm2 = { kind = "coreos"; transport = "9p"; container = "coreos-store-matrix-vm2"; sshPort = 2223; reusePrimary = false; };
  };
  workloads = builtins.listToAttrs (builtins.concatMap
    (placement: map (replica: {
      name = "shared-${placement}-${replica}";
      value = { inherit placement; domain = "common"; access = "read-only"; };
    }) [ "a" "b" ]) [ "host" "vm1" "vm2" ]);
}
