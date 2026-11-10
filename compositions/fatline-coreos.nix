{ system, profile ? "vm1" }:
assert builtins.elem profile [ "vm1" "vm2" ];
let vm2 = profile == "vm2"; in
{
  schema = 1;
  inherit system;
  scope = "fatline-arm-${profile}";
  logicalSource = "us:${profile}";
  sources.agni = {
    repository = "dash-xd/agni";
    revision = if vm2 then "8701db66119eef70307860f09cdef02a947caa87" else "dee1aa14b41e7fe4094d7b007a3ecb702d6f8759";
    flakeDirectory = "local/fatline";
    package = "host-link-${profile}";
  };
  guestAdapter = {
    repository = "dash-xd/agni";
    revision = "de1086a0ab9f6bf412c2b9788b04dc2cafc4b251";
    sha256 = "8b763250cc1e35b761d069be814e1354dbcabaf0a8eb12c98ba7a825adf09a5b";
    contract = "fatline-host-link-v1";
    compatibleRuntimeRevision = if vm2 then "8701db66119eef70307860f09cdef02a947caa87" else "dee1aa14b41e7fe4094d7b007a3ecb702d6f8759";
  };
  services = {
    repository = "dash-xd/agni";
    revision = if vm2 then "b801e613a35d8eacd3cc7ca9cf469c0b084e4cf7" else "28465d99258c972abe29cad21eebef327a623415";
    refreshFrom = [ "1608001b6fb1c57ad7481b7786c5a9a5e3c4932f" ];
    package = "coreos-services-vm1";
    contract = "coreos-services-v1";
  };
  servicesProbe = {
    repository = "dash-xd/agni";
    revision = "b801e613a35d8eacd3cc7ca9cf469c0b084e4cf7";
    package = "coreos-services-vm1";
    contract = "coreos-services-v1";
  };
  servicesRecovery = {
    repository = "dash-xd/agni";
    revision = "0229581143c0e122ef1e92faba67f188ddb06f0f";
    refreshFrom = [ "202e64ccaff67fd36a5511bb8e88a28719cd9831" ];
    package = "coreos-services-vm1";
    contract = "coreos-services-v1";
  };
  placement = {
    name = profile;
    kind = "coreos";
    container = if vm2 then "coreos-store-matrix-vm2" else "coreos-starwisp";
    sshPort = if vm2 then 2223 else 2222;
    reusePrimary = !vm2;
  };
  ingress = {
    transport = "ssh-tcp-nginx-unix";
    hostPort = if vm2 then 26379 else 16379;
    guestProxyPort = 16379;
  };
  storeDomain = "common";
  fullFatlineQualified = false;
}
